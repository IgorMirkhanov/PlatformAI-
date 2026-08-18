"""Prompt template CRUD + safe Jinja2 rendering."""

from __future__ import annotations

import re
import uuid
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, UndefinedError, meta
from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm.prompt_template import PromptTemplate

_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-]{1,127}$")


class PromptServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class PromptNotFoundError(PromptServiceError):
    def __init__(self, message: str = "Prompt template not found.") -> None:
        super().__init__(message, status_code=404)


class PromptConflictError(PromptServiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=409)


class PromptVariableMissingError(PromptServiceError):
    """Raised when Jinja2 requires a variable absent from the render context."""

    def __init__(
        self,
        message: str,
        *,
        variable: str | None = None,
        template_name: str | None = None,
    ) -> None:
        super().__init__(message, status_code=422)
        self.variable = variable
        self.template_name = template_name


class PromptTemplateSyntaxError(PromptServiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400)


def _jinja_env() -> Environment:
    return Environment(
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _validate_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not _NAME_RE.match(cleaned):
        raise PromptServiceError(
            "Invalid template name. Use 2–128 chars: letters, digits, underscore, hyphen; "
            "must start with a letter."
        )
    return cleaned


def _validate_content(content: str) -> str:
    text = content if content is not None else ""
    if not str(text).strip():
        raise PromptServiceError("Template content must not be empty.")
    # Fail fast on syntax errors at write-time.
    try:
        _jinja_env().parse(text)
    except TemplateSyntaxError as exc:
        raise PromptTemplateSyntaxError(f"Invalid Jinja2 template: {exc}") from exc
    return text


class PromptTemplateService:
    """Tenant-aware prompt library with versioned updates and strict render."""

    async def list_templates(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        include_global: bool = True,
        active_only: bool = True,
    ) -> list[PromptTemplate]:
        clauses = [PromptTemplate.organization_id == organization_id]
        if include_global:
            clauses = [
                or_(
                    PromptTemplate.organization_id == organization_id,
                    PromptTemplate.organization_id.is_(None),
                )
            ]
        stmt = select(PromptTemplate).where(*clauses)
        if active_only:
            stmt = stmt.where(PromptTemplate.is_active.is_(True))
        stmt = stmt.order_by(PromptTemplate.name.asc(), PromptTemplate.version.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(
        self,
        db: AsyncSession,
        template_id: uuid.UUID,
        organization_id: uuid.UUID,
        *,
        allow_global: bool = True,
    ) -> PromptTemplate:
        template = await db.get(PromptTemplate, template_id)
        if template is None:
            raise PromptNotFoundError()
        if template.organization_id is None:
            if not allow_global:
                raise PromptNotFoundError()
            return template
        if template.organization_id != organization_id:
            raise PromptNotFoundError()
        return template

    async def get_by_name(
        self,
        db: AsyncSession,
        name: str,
        organization_id: uuid.UUID,
        *,
        active_only: bool = True,
    ) -> PromptTemplate:
        cleaned = _validate_name(name)
        stmt = (
            select(PromptTemplate)
            .where(
                PromptTemplate.name == cleaned,
                PromptTemplate.organization_id == organization_id,
            )
            .limit(1)
        )
        if active_only:
            stmt = stmt.where(PromptTemplate.is_active.is_(True))
        result = await db.execute(stmt)
        template = result.scalar_one_or_none()
        if template is not None:
            return template

        # Fallback to global/system template with the same name.
        global_stmt = (
            select(PromptTemplate)
            .where(
                PromptTemplate.name == cleaned,
                PromptTemplate.organization_id.is_(None),
            )
            .limit(1)
        )
        if active_only:
            global_stmt = global_stmt.where(PromptTemplate.is_active.is_(True))
        result = await db.execute(global_stmt)
        template = result.scalar_one_or_none()
        if template is None:
            raise PromptNotFoundError(f"Prompt template '{cleaned}' not found.")
        return template

    async def create(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        name: str,
        content: str,
        description: str | None = None,
        created_by_id: uuid.UUID | None = None,
    ) -> PromptTemplate:
        cleaned_name = _validate_name(name)
        cleaned_content = _validate_content(content)

        existing = await db.execute(
            select(PromptTemplate.id).where(
                PromptTemplate.organization_id == organization_id,
                PromptTemplate.name == cleaned_name,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise PromptConflictError(
                f"Prompt template '{cleaned_name}' already exists in this organization."
            )

        template = PromptTemplate(
            id=uuid.uuid4(),
            organization_id=organization_id,
            name=cleaned_name,
            version=1,
            content=cleaned_content,
            description=(description.strip() if description else None) or None,
            is_active=True,
            created_by_id=created_by_id,
        )
        db.add(template)
        await db.flush()
        await db.commit()
        await db.refresh(template)
        logger.info(
            "Prompt.create | org={org} name={name} id={id}",
            org=organization_id,
            name=cleaned_name,
            id=template.id,
        )
        return template

    async def update(
        self,
        db: AsyncSession,
        template_id: uuid.UUID,
        organization_id: uuid.UUID,
        *,
        content: str | None = None,
        description: str | None = None,
        name: str | None = None,
        is_active: bool | None = None,
    ) -> PromptTemplate:
        template = await self.get_by_id(
            db, template_id, organization_id, allow_global=False
        )
        bumped = False

        if name is not None:
            cleaned_name = _validate_name(name)
            if cleaned_name != template.name:
                clash = await db.execute(
                    select(PromptTemplate.id).where(
                        PromptTemplate.organization_id == organization_id,
                        PromptTemplate.name == cleaned_name,
                        PromptTemplate.id != template.id,
                    )
                )
                if clash.scalar_one_or_none() is not None:
                    raise PromptConflictError(
                        f"Prompt template '{cleaned_name}' already exists."
                    )
                template.name = cleaned_name
                bumped = True

        if content is not None:
            cleaned_content = _validate_content(content)
            if cleaned_content != template.content:
                template.content = cleaned_content
                bumped = True

        if description is not None:
            new_desc = description.strip() or None
            if new_desc != template.description:
                template.description = new_desc
                bumped = True

        if is_active is not None and bool(is_active) != bool(template.is_active):
            template.is_active = bool(is_active)
            bumped = True

        if bumped:
            template.version = int(template.version or 1) + 1

        await db.flush()
        await db.commit()
        await db.refresh(template)
        logger.info(
            "Prompt.update | org={org} id={id} version={version}",
            org=organization_id,
            id=template.id,
            version=template.version,
        )
        return template

    async def delete(
        self,
        db: AsyncSession,
        template_id: uuid.UUID,
        organization_id: uuid.UUID,
        *,
        hard: bool = False,
    ) -> None:
        template = await self.get_by_id(
            db, template_id, organization_id, allow_global=False
        )
        if hard:
            await db.delete(template)
        else:
            if template.is_active:
                template.is_active = False
                template.version = int(template.version or 1) + 1
        await db.flush()
        await db.commit()
        logger.info(
            "Prompt.delete | org={org} id={id} hard={hard}",
            org=organization_id,
            id=template_id,
            hard=hard,
        )

    def render_content(
        self,
        content: str,
        context: dict[str, Any],
        *,
        template_name: str | None = None,
    ) -> str:
        """Render Jinja2 content with StrictUndefined (missing vars → error)."""
        env = _jinja_env()
        try:
            ast = env.parse(content)
            required = meta.find_undeclared_variables(ast)
            missing = sorted(var for var in required if var not in (context or {}))
            if missing:
                var = missing[0]
                logger.warning(
                    "Prompt.render_missing | template={name} variable={var} missing={all}",
                    name=template_name,
                    var=var,
                    all=missing,
                )
                raise PromptVariableMissingError(
                    f"Missing required template variable: '{var}'.",
                    variable=var,
                    template_name=template_name,
                )
            rendered = env.from_string(content).render(**(context or {}))
        except PromptVariableMissingError:
            raise
        except UndefinedError as exc:
            # Nested attribute access (e.g. contact.name) when parent exists but attr does not.
            logger.warning(
                "Prompt.render_undefined | template={name} error={error}",
                name=template_name,
                error=str(exc),
            )
            raise PromptVariableMissingError(
                f"Undefined template variable: {exc}",
                template_name=template_name,
            ) from exc
        except TemplateSyntaxError as exc:
            raise PromptTemplateSyntaxError(f"Invalid Jinja2 template: {exc}") from exc
        return rendered

    async def render_template(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        context: dict[str, Any],
        *,
        template_id: uuid.UUID | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        if template_id is not None:
            template = await self.get_by_id(db, template_id, organization_id)
        elif name:
            template = await self.get_by_name(db, name, organization_id)
        else:
            raise PromptServiceError("Either template_id or name is required.")

        if not template.is_active:
            raise PromptServiceError(
                "Prompt template is inactive.",
                status_code=409,
            )

        rendered = self.render_content(
            template.content,
            context or {},
            template_name=template.name,
        )
        return {
            "template_id": template.id,
            "name": template.name,
            "version": template.version,
            "rendered": rendered,
        }


prompt_template_service = PromptTemplateService()
