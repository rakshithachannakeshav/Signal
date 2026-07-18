/**
 * Avatar.tsx
 * Renders a user/conversation avatar image, or — when no image URL is set —
 * a deterministic colored initial-letter fallback (same name always maps to
 * the same color, so a contact's fallback avatar doesn't change every render).
 */
'use client';

import React from 'react';

const FALLBACK_COLORS = ['#e11d48', '#2563eb', '#16a34a', '#d97706', '#9333ea', '#0891b2', '#ea580c'];

interface AvatarProps {
  url?: string | null;
  name: string;
  sizeClass?: string;
}

export default function Avatar({ url, name, sizeClass = 'w-10 h-10' }: AvatarProps) {
  if (url && url.trim() !== '') {
    return <img src={url} className={`${sizeClass} rounded-full object-cover`} alt={name} />;
  }

  const initial = name ? name.charAt(0).toUpperCase() : '?';
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const color = FALLBACK_COLORS[Math.abs(hash) % FALLBACK_COLORS.length];

  return (
    <div
      className={`${sizeClass} rounded-full flex items-center justify-center text-white font-bold select-none`}
      style={{ backgroundColor: color, fontSize: sizeClass.includes('w-11') ? '16px' : sizeClass.includes('w-8') ? '11px' : '13px' }}
    >
      {initial}
    </div>
  );
}
