"use client";

import { useId } from "react";

import type { HubChannelType } from "@/types/channel-hub";

interface HubChannelBrandIconProps {
  channelId: HubChannelType;
  className?: string;
}

/** Brand marks for Omnichannel Hub cards (same visual language as channel logos). */
export function HubChannelBrandIcon({
  channelId,
  className = "h-6 w-6",
}: HubChannelBrandIconProps) {
  const reactId = useId().replace(/:/g, "");
  const igGradientId = `hub-ig-${reactId}`;

  switch (channelId) {
    case "telegram":
    case "telegram_business":
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle
            cx="12"
            cy="12"
            r="12"
            fill={channelId === "telegram_business" ? "#5AC8FA" : "#229ED9"}
          />
          <path
            d="M5.5 11.8c3.9-1.7 6.5-2.8 7.8-3.4 3.7-1.5 4.5-1.8 5-1.8.1 0 .3.1.3.3 0 .1 0 .2-.1.3-.4.9-2.2 5.4-2.5 6.1-.1.2-.2.3-.4.3-.1 0-.2 0-3.2-1.2-.6-.3-1.1-.4-1.2-.4-.1 0-.2 0-.3.1l-1.7 1.6c-.1.1-.2.1-.3.1-.1 0-.2-.1-.3-.2l-.8-1.5c-.1-.2-.2-.2-.3-.2H5.8c-.2 0-.3-.1-.3-.2 0-.1.1-.2.2-.3l-.2-.1z"
            fill="#fff"
          />
        </svg>
      );
    case "whatsapp_qr":
    case "waba":
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle
            cx="12"
            cy="12"
            r="12"
            fill={channelId === "waba" ? "#128C7E" : "#25D366"}
          />
          <path
            d="M17.5 14.1c-.3-.1-1.6-.8-1.8-.9-.3-.1-.5-.1-.7.1-.2.3-.8.9-1 1.1-.2.2-.4.2-.7.1-.3-.1-1.3-.5-2.4-1.6-.9-.8-1.5-1.8-1.7-2.1-.2-.3 0-.5.1-.6.1-.1.3-.3.4-.5.1-.2.1-.3.2-.5.1-.2 0-.4 0-.5 0-.1-.7-1.7-1-2.3-.3-.6-.5-.5-.7-.5h-.6c-.2 0-.5.1-.7.3-.2.3-.9.9-.9 2.1 0 1.2.9 2.4 1 2.6.1.2 1.8 2.7 4.3 3.8.6.3 1.1.4 1.5.5.6.2 1.2.2 1.6.1.5-.1 1.6-.7 1.8-1.3.2-.6.2-1.1.1-1.3-.1-.2-.3-.3-.6-.4z"
            fill="#fff"
          />
        </svg>
      );
    case "instagram":
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <defs>
            <linearGradient id={igGradientId} x1="0%" y1="100%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#FD5949" />
              <stop offset="50%" stopColor="#D6249F" />
              <stop offset="100%" stopColor="#285AEB" />
            </linearGradient>
          </defs>
          <rect x="2" y="2" width="20" height="20" rx="6" fill={`url(#${igGradientId})`} />
          <circle cx="12" cy="12" r="4.2" stroke="#fff" strokeWidth="1.6" fill="none" />
          <circle cx="17.2" cy="6.8" r="1.2" fill="#fff" />
        </svg>
      );
    case "wazzup":
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="2" y="2" width="20" height="20" rx="6" fill="#7C3AED" />
          <path
            d="M7 8.5h10M7 12h6.5M7 15.5h8"
            stroke="#fff"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
          <circle cx="16.5" cy="15.5" r="2" fill="#fff" />
        </svg>
      );
    case "calls":
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="12" fill="#F59E0B" />
          <path
            d="M15.6 14.3c-.3-.1-.9-.4-1-.5-.2-.1-.3-.1-.4.1-.1.2-.5.5-.6.6-.1.1-.2.1-.4 0-.2-.1-.7-.3-1.4-.9-.5-.5-.9-1.1-1-1.3-.1-.2 0-.3.1-.4l.3-.3c.1-.1.1-.2.1-.3 0-.1-.4-1-.5-1.3-.1-.4-.3-.3-.4-.3h-.3c-.1 0-.3 0-.4.2-.1.2-.5.5-.5 1.2 0 .7.5 1.4.6 1.5.1.1 1 1.6 2.5 2.2.3.1.6.2.9.3.4.1.7.1.9.1.3 0 .9-.4 1-.8.1-.3.1-.6.1-.7 0-.1-.1-.2-.3-.3z"
            fill="#fff"
          />
        </svg>
      );
    case "api":
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="2" y="2" width="20" height="20" rx="6" fill="#6366F1" />
          <path
            d="M8 9.2 5.8 12 8 14.8M16 9.2 18.2 12 16 14.8M13.2 8l-2.4 8"
            stroke="#fff"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "web_widget":
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="2" y="4" width="20" height="16" rx="4" fill="#8B5CF6" />
          <path
            d="M7 9h10M7 12.5h6"
            stroke="#fff"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
          <circle cx="17.5" cy="15.5" r="2.5" fill="#fff" fillOpacity="0.9" />
        </svg>
      );
    default:
      return null;
  }
}
