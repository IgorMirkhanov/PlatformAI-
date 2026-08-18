import type { ChannelIntegrationType } from "@/types/channels";

interface ChannelBrandIconProps {
  channelId: ChannelIntegrationType;
  className?: string;
}

export function ChannelBrandIcon({ channelId, className = "h-6 w-6" }: ChannelBrandIconProps) {
  switch (channelId) {
    case "telegram":
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="12" fill="#229ED9" />
          <path
            d="M5.5 11.8c3.9-1.7 6.5-2.8 7.8-3.4 3.7-1.5 4.5-1.8 5-1.8.1 0 .3.1.3.3 0 .1 0 .2-.1.3-.4.9-2.2 5.4-2.5 6.1-.1.2-.2.3-.4.3-.1 0-.2 0-3.2-1.2-.6-.3-1.1-.4-1.2-.4-.1 0-.2 0-.3.1l-1.7 1.6c-.1.1-.2.1-.3.1-.1 0-.2-.1-.3-.2l-.8-1.5c-.1-.2-.2-.2-.3-.2H5.8c-.2 0-.3-.1-.3-.2 0-.1.1-.2.2-.3l-.2-.1z"
            fill="#fff"
          />
        </svg>
      );
    case "whatsapp":
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="12" fill="#25D366" />
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
            <linearGradient id="ig-gradient" x1="0%" y1="100%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#FD5949" />
              <stop offset="50%" stopColor="#D6249F" />
              <stop offset="100%" stopColor="#285AEB" />
            </linearGradient>
          </defs>
          <rect x="2" y="2" width="20" height="20" rx="6" fill="url(#ig-gradient)" />
          <circle cx="12" cy="12" r="4.2" stroke="#fff" strokeWidth="1.6" fill="none" />
          <circle cx="17.2" cy="6.8" r="1.2" fill="#fff" />
        </svg>
      );
    case "vkontakte":
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="12" fill="#0077FF" />
          <path
            d="M12.8 16.5h-.9c-.3 0-.5-.1-.7-.4-1.1-1.5-2.3-2.7-3.5-3.6-.2-.2-.4-.2-.6 0v3.9c0 .3-.2.5-.5.5H5.8c-.3 0-.5-.2-.5-.5V7.5c0-.3.2-.5.5-.5h1.3c.3 0 .5.2.5.5v3.1c0 .3.1.4.3.3 1-.8 1.9-2 2.7-3.5.1-.2.3-.4.6-.4h1.5c.4 0 .5.2.4.5-.5 1.1-1.3 2.2-2.3 3.2 1.2 1.1 2.2 2.5 3 4.1.2.3.1.5-.2.5z"
            fill="#fff"
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
