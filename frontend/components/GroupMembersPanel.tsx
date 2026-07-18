/**
 * GroupMembersPanel.tsx
 * Drawer showing a group's member list, plus admin controls to add or
 * remove members, and a "Leave Group" action available to any member.
 * Renders as a full-screen overlay on mobile (below `md`) and a fixed-width
 * side drawer on desktop, matching the rest of ChatLayout's responsive
 * pattern for panels.
 */
'use client';

import React, { useState, useEffect } from 'react';
import { X, UserPlus, UserMinus, LogOut } from 'lucide-react';
import { api } from '@/lib/api';
import { Conversation, User } from '@/lib/types';
import Avatar from './Avatar';

interface GroupMembersPanelProps {
  conversation: Conversation;
  currentUser: User;
  onClose: () => void;
  onConversationUpdated: (conversation: Conversation) => void;
}

export default function GroupMembersPanel({ conversation, currentUser, onClose, onConversationUpdated }: GroupMembersPanelProps) {
  const [contacts, setContacts] = useState<any[]>([]);
  const [showAddPicker, setShowAddPicker] = useState(false);
  const [busyUserId, setBusyUserId] = useState<number | null>(null);
  const [error, setError] = useState('');

  const myMembership = conversation.members.find((m) => m.user_id === currentUser.id);
  const isAdmin = myMembership?.role === 'admin';

  // Only fetch the contact list when the add-picker is actually opened —
  // most drawer opens are just to glance at who's in the group.
  useEffect(() => {
    if (showAddPicker) {
      api.getContacts().then(setContacts).catch(() => setContacts([]));
    }
  }, [showAddPicker]);

  const memberIds = new Set(conversation.members.map((m) => m.user_id));
  const addableContacts = contacts.filter((c) => !memberIds.has(c.contact_user.id));

  const handleAdd = async (userId: number) => {
    setBusyUserId(userId);
    setError('');
    try {
      const updated = await api.addMember(conversation.id, userId);
      onConversationUpdated(updated);
    } catch (err: any) {
      setError(err.message || 'Failed to add member');
    } finally {
      setBusyUserId(null);
    }
  };

  const handleRemove = async (userId: number) => {
    setBusyUserId(userId);
    setError('');
    try {
      const updated = await api.removeMember(conversation.id, userId);
      onConversationUpdated(updated);
    } catch (err: any) {
      setError(err.message || 'Failed to remove member');
    } finally {
      setBusyUserId(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-40 w-full md:static md:inset-auto md:z-auto md:w-64 flex flex-col flex-shrink-0"
      style={{ backgroundColor: 'var(--surface)', borderLeft: '1px solid var(--border)' }}
    >
      <div className="p-4 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
        <h3 className="font-bold text-sm" style={{ color: 'var(--text)' }}>Group Members</h3>
        <button
          onClick={() => { onClose(); setShowAddPicker(false); }}
          className="p-1 rounded"
          style={{ color: 'var(--muted)', background: 'transparent', border: 'none', cursor: 'pointer' }}
          onMouseEnter={(e) => (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--surface2)'}
          onMouseLeave={(e) => (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent'}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {error && (
        <div style={{ padding: '8px 16px', fontSize: 11, background: 'rgba(239,68,68,0.12)', color: '#f87171' }}>
          {error}
        </div>
      )}

      {isAdmin && (
        <div className="p-3" style={{ borderBottom: '1px solid var(--border)' }}>
          <button
            onClick={() => setShowAddPicker((prev) => !prev)}
            className="w-full flex items-center justify-center gap-2 text-xs font-semibold py-2 rounded-lg"
            style={{ background: 'rgba(58,118,240,0.12)', color: '#3a76f0', border: 'none', cursor: 'pointer' }}
          >
            <UserPlus size={13} /> Add Member
          </button>
          {showAddPicker && (
            <div className="mt-2 space-y-1 max-h-40 overflow-y-auto">
              {addableContacts.length === 0 ? (
                <p className="text-[11px] text-center py-2" style={{ color: 'var(--muted)' }}>No contacts left to add.</p>
              ) : addableContacts.map((c) => (
                <div
                  key={c.contact_user.id}
                  onClick={() => handleAdd(c.contact_user.id)}
                  className="flex items-center gap-2 p-1.5 rounded-lg cursor-pointer"
                  onMouseEnter={(e) => (e.currentTarget as HTMLDivElement).style.backgroundColor = 'var(--surface2)'}
                  onMouseLeave={(e) => (e.currentTarget as HTMLDivElement).style.backgroundColor = 'transparent'}
                >
                  <Avatar url={c.contact_user.avatar_url} name={c.contact_user.display_name} sizeClass="w-6 h-6" />
                  <span className="text-xs font-medium truncate" style={{ color: 'var(--text)' }}>{c.contact_user.display_name}</span>
                  {busyUserId === c.contact_user.id && <span className="text-[10px] ml-auto" style={{ color: 'var(--muted)' }}>Adding…</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {conversation.members.map((member) => {
          const isMe = member.user_id === currentUser.id;
          const canRemove = isAdmin && !isMe;
          return (
            <div
              key={member.id}
              className="flex items-center space-x-3 p-1.5 rounded-lg"
              style={{ cursor: 'default' }}
              onMouseEnter={(e) => (e.currentTarget as HTMLDivElement).style.backgroundColor = 'var(--surface2)'}
              onMouseLeave={(e) => (e.currentTarget as HTMLDivElement).style.backgroundColor = 'transparent'}
            >
              <Avatar url={member.user.avatar_url} name={member.user.display_name} sizeClass="w-8 h-8" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold truncate" style={{ color: 'var(--text)' }}>{member.user.display_name}</p>
                <p className="text-[9px] font-mono" style={{ color: 'var(--muted)' }}>@{member.user.phone_or_username}</p>
              </div>
              {member.role === 'admin' && (
                <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded" style={{ background: 'rgba(58,118,240,0.12)', color: '#3a76f0', border: '1px solid rgba(58,118,240,0.25)' }}>
                  Admin
                </span>
              )}
              {canRemove && (
                <button
                  onClick={() => handleRemove(member.user_id)}
                  disabled={busyUserId === member.user_id}
                  title="Remove from group"
                  style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--muted)', padding: 2 }}
                  onMouseEnter={(e) => (e.currentTarget as HTMLButtonElement).style.color = '#ef4444'}
                  onMouseLeave={(e) => (e.currentTarget as HTMLButtonElement).style.color = 'var(--muted)'}
                >
                  <UserMinus size={14} />
                </button>
              )}
              {isMe && (
                <button
                  onClick={() => handleRemove(member.user_id)}
                  disabled={busyUserId === member.user_id}
                  title="Leave group"
                  style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: '#ef4444', padding: 2 }}
                >
                  <LogOut size={14} />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
