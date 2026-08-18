"use client";

import {
  useCallback,
  useEffect,
  useState,
  type ChangeEvent,
  type FocusEvent,
  type KeyboardEvent,
  type TextareaHTMLAttributes,
  type InputHTMLAttributes,
} from "react";

import { cn } from "@/lib/utils";
import {
  flowFieldClassName,
  flowTextareaClassName,
} from "@/components/flow/nodes/FlowNodeShell";

/** Stop React Flow from treating Backspace/Delete as node deletion. */
export function stopFlowKeyboardPropagation(
  event: KeyboardEvent<HTMLElement>,
): void {
  event.stopPropagation();
}

/**
 * Local buffered text field that commits to the store on blur (or Enter for inputs).
 * Avoids re-rendering the entire canvas on every keystroke via onNodesChange/data updates.
 */
export function useLocalNodeField(
  externalValue: string,
  onCommit: (value: string) => void,
) {
  const [value, setValue] = useState(externalValue);

  useEffect(() => {
    setValue(externalValue);
  }, [externalValue]);

  const commit = useCallback(() => {
    if (value !== externalValue) {
      onCommit(value);
    }
  }, [externalValue, onCommit, value]);

  const onChange = useCallback(
    (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setValue(event.target.value);
    },
    [],
  );

  const onBlur = useCallback(
    (_event: FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      commit();
    },
    [commit],
  );

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      stopFlowKeyboardPropagation(event);
      if (event.key === "Enter" && event.currentTarget.tagName === "INPUT") {
        event.currentTarget.blur();
      }
    },
    [],
  );

  return { value, onChange, onBlur, onKeyDown, setValue, commit };
}

type LocalInputProps = InputHTMLAttributes<HTMLInputElement> & {
  externalValue: string;
  onCommit: (value: string) => void;
};

export function LocalNodeInput({
  externalValue,
  onCommit,
  className,
  ...props
}: LocalInputProps) {
  const field = useLocalNodeField(externalValue, onCommit);
  return (
    <input
      {...props}
      value={field.value}
      onChange={field.onChange}
      onBlur={field.onBlur}
      onKeyDown={field.onKeyDown}
      onKeyUp={stopFlowKeyboardPropagation}
      className={cn(flowFieldClassName, className)}
    />
  );
}

type LocalTextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  externalValue: string;
  onCommit: (value: string) => void;
};

export function LocalNodeTextarea({
  externalValue,
  onCommit,
  className,
  ...props
}: LocalTextareaProps) {
  const field = useLocalNodeField(externalValue, onCommit);
  return (
    <textarea
      {...props}
      value={field.value}
      onChange={field.onChange}
      onBlur={field.onBlur}
      onKeyDown={field.onKeyDown}
      onKeyUp={stopFlowKeyboardPropagation}
      className={cn(flowTextareaClassName, className)}
    />
  );
}
