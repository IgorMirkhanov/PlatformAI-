"use client";

import { useState } from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

interface TagsChipInputProps {
  value: string[];
  onChange: (tags: string[]) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function TagsChipInput({
  value,
  onChange,
  disabled = false,
  placeholder = "Добавить тег и Enter",
}: TagsChipInputProps) {
  const [draft, setDraft] = useState("");

  const addTag = (raw: string): void => {
    const trimmed = raw.trim();
    if (!trimmed || value.includes(trimmed)) {
      return;
    }
    onChange([...value, trimmed]);
    setDraft("");
  };

  return (
    <div className="rounded-xl border border-zinc-800/80 bg-black/30 p-3">
      <div className="flex flex-wrap gap-2">
        {value.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 rounded-full bg-violet-500/10 px-2.5 py-1 text-xs font-medium text-violet-200 ring-1 ring-violet-500/20"
          >
            {tag}
            {!disabled ? (
              <button
                type="button"
                onClick={() => onChange(value.filter((item) => item !== tag))}
                className="text-violet-300/80 hover:text-violet-100"
                aria-label={`Удалить тег ${tag}`}
              >
                <X className="h-3 w-3" />
              </button>
            ) : null}
          </span>
        ))}
      </div>
      <input
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            addTag(draft);
          }
        }}
        onBlur={() => addTag(draft)}
        placeholder={placeholder}
        className={cn(
          "mt-2 w-full bg-transparent text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none",
          disabled && "opacity-50",
        )}
      />
    </div>
  );
}
