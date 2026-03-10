"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useSession } from "next-auth/react";
import {
  MessageSquare,
  Send,
  Loader2,
  Pin,
  CornerDownRight,
  MoreHorizontal,
  Link2,
  Pencil,
  Check,
  X,
} from "lucide-react";
import { usePusherEvent } from "@/hooks/usePusher";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Comment {
  _id: string;
  grant_id: string;
  user_name: string;
  user_email?: string;
  user_image?: string;
  message: string;
  created_at: string;
  parent_id: string | null;
  pinned: boolean;
  pinned_at?: string | null;
  pinned_by?: string | null;
  reactions: Record<string, string[]>;
  edited_at?: string | null;
}

interface CommentThreadProps {
  grantId: string;
}

const REACTION_PALETTE = ["👍", "❤️", "👀", "🔥", "🎉", "🤔"];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function timeAgo(iso: string): string {
  const seconds = Math.floor(
    (Date.now() - new Date(iso).getTime()) / 1000
  );
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function Avatar({
  name,
  image,
  size = "sm",
}: {
  name: string;
  image?: string;
  size?: "sm" | "md";
}) {
  const s = size === "md" ? "h-7 w-7 text-xs" : "h-5 w-5 text-[10px]";
  if (image) {
    return (
      <img
        src={image}
        alt=""
        className={`${s} rounded-full object-cover ring-1 ring-gray-200`}
        referrerPolicy="no-referrer"
      />
    );
  }
  return (
    <div
      className={`${s} flex items-center justify-center rounded-full bg-blue-100 font-bold text-blue-600`}
    >
      {(name || "?")[0].toUpperCase()}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export function CommentThread({ grantId }: CommentThreadProps) {
  const { data: session } = useSession();
  const [comments, setComments] = useState<Comment[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [replyMessage, setReplyMessage] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editMessage, setEditMessage] = useState("");
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [reactionPickerFor, setReactionPickerFor] = useState<string | null>(null);
  const [copiedLink, setCopiedLink] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const userName = session?.user?.name ?? "Team Member";
  const userEmail = session?.user?.email ?? "";
  const userImage = session?.user?.image ?? "";

  /* ── Fetch ─────────────────────────────────────────────────────── */

  const fetchComments = useCallback(async () => {
    try {
      const res = await fetch(`/api/grants/${grantId}/comments`);
      if (!res.ok) throw new Error("Failed to fetch");
      const data: Comment[] = await res.json();
      setComments(data);
    } catch {
      /* empty state */
    } finally {
      setLoading(false);
    }
  }, [grantId]);

  useEffect(() => {
    setLoading(true);
    setComments([]);
    setReplyTo(null);
    setEditingId(null);
    setOpenMenu(null);
    fetchComments();
  }, [fetchComments]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [comments]);

  /* ── Close menu on outside click ───────────────────────────────── */

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
        setReactionPickerFor(null);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  /* ── Pusher real-time ──────────────────────────────────────────── */

  usePusherEvent(`grant-${grantId}`, "comment:new", (data) => {
    const payload = data as { comment: Comment };
    setComments((prev) => {
      if (prev.some((c) => c._id === payload.comment._id)) return prev;
      return [...prev, payload.comment];
    });
  });

  usePusherEvent(`grant-${grantId}`, "comment:pin", (data) => {
    const payload = data as { commentId: string; pinned: boolean; pinned_by?: string };
    setComments((prev) =>
      prev.map((c) =>
        c._id === payload.commentId
          ? { ...c, pinned: payload.pinned, pinned_by: payload.pinned_by ?? null }
          : c
      )
    );
  });

  usePusherEvent(`grant-${grantId}`, "comment:react", (data) => {
    const payload = data as { commentId: string; reactions: Record<string, string[]> };
    setComments((prev) =>
      prev.map((c) =>
        c._id === payload.commentId ? { ...c, reactions: payload.reactions } : c
      )
    );
  });

  usePusherEvent(`grant-${grantId}`, "comment:edit", (data) => {
    const payload = data as { commentId: string; message: string; edited_at: string };
    setComments((prev) =>
      prev.map((c) =>
        c._id === payload.commentId
          ? { ...c, message: payload.message, edited_at: payload.edited_at }
          : c
      )
    );
  });

  /* ── Actions ───────────────────────────────────────────────────── */

  const handleSend = async (parentId?: string | null) => {
    const text = parentId ? replyMessage.trim() : message.trim();
    if (!text || sending) return;

    setSending(true);
    try {
      const res = await fetch(`/api/grants/${grantId}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_name: userName,
          user_email: userEmail,
          user_image: userImage,
          message: text,
          parent_id: parentId || null,
        }),
      });
      if (!res.ok) throw new Error("Failed to post");
      if (parentId) {
        setReplyMessage("");
        setReplyTo(null);
      } else {
        setMessage("");
      }
      await fetchComments();
    } catch {
      /* swallow */
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
  };

  const handlePin = async (commentId: string, pinned: boolean) => {
    setOpenMenu(null);
    await fetch(`/api/grants/${grantId}/comments/${commentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: pinned ? "unpin" : "pin",
        user_email: userEmail,
      }),
    });
    await fetchComments();
  };

  const handleReact = async (commentId: string, emoji: string) => {
    setReactionPickerFor(null);
    const comment = comments.find((c) => c._id === commentId);
    const already = comment?.reactions?.[emoji]?.includes(userEmail);
    await fetch(`/api/grants/${grantId}/comments/${commentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: already ? "unreact" : "react",
        emoji,
        user_email: userEmail,
      }),
    });
    await fetchComments();
  };

  const handleEdit = async (commentId: string) => {
    const trimmed = editMessage.trim();
    if (!trimmed) return;
    await fetch(`/api/grants/${grantId}/comments/${commentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "edit",
        message: trimmed,
        user_email: userEmail,
      }),
    });
    setEditingId(null);
    setEditMessage("");
    await fetchComments();
  };

  const handleCopyLink = (commentId: string) => {
    const url = `${window.location.origin}/dashboard?grant=${grantId}&comment=${commentId}`;
    navigator.clipboard.writeText(url);
    setCopiedLink(commentId);
    setOpenMenu(null);
    setTimeout(() => setCopiedLink(null), 2000);
  };

  const handleKeyDown = (
    e: React.KeyboardEvent<HTMLTextAreaElement>,
    parentId?: string | null
  ) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend(parentId);
    }
  };

  /* ── Group comments ────────────────────────────────────────────── */

  const topLevel = comments.filter((c) => !c.parent_id);
  const repliesMap: Record<string, Comment[]> = {};
  comments
    .filter((c) => c.parent_id)
    .forEach((c) => {
      if (!repliesMap[c.parent_id!]) repliesMap[c.parent_id!] = [];
      repliesMap[c.parent_id!].push(c);
    });

  const pinnedComments = topLevel.filter((c) => c.pinned);
  const unpinnedComments = topLevel.filter((c) => !c.pinned);

  /* ── Render helpers ────────────────────────────────────────────── */

  const renderReactions = (comment: Comment) => {
    const reactions = comment.reactions ?? {};
    const entries = Object.entries(reactions).filter(
      ([, users]) => users && users.length > 0
    );
    if (entries.length === 0) return null;

    return (
      <div className="mt-1.5 flex flex-wrap gap-1">
        {entries.map(([emoji, users]) => {
          const isMine = users.includes(userEmail);
          return (
            <button
              key={emoji}
              onClick={() => handleReact(comment._id, emoji)}
              className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors ${
                isMine
                  ? "border-blue-200 bg-blue-50 text-blue-700"
                  : "border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100"
              }`}
            >
              <span>{emoji}</span>
              <span className="font-medium">{users.length}</span>
            </button>
          );
        })}
      </div>
    );
  };

  const renderCommentBubble = (c: Comment, isReply = false) => {
    const isMe = c.user_email === userEmail && !!userEmail;
    const isEditing = editingId === c._id;

    return (
      <div
        key={c._id}
        id={`comment-${c._id}`}
        className={`group relative ${isReply ? "ml-8" : ""}`}
      >
        <div className="flex gap-2.5">
          <div className="mt-0.5 shrink-0">
            <Avatar
              name={c.user_name}
              image={c.user_image}
              size={isReply ? "sm" : "md"}
            />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2">
              <span className="text-xs font-semibold text-gray-800">
                {c.user_name}
                {isMe && (
                  <span className="ml-1 text-[10px] font-normal text-gray-400">
                    (you)
                  </span>
                )}
              </span>
              <span className="text-[10px] text-gray-400">
                {timeAgo(c.created_at)}
              </span>
              {c.edited_at && (
                <span className="text-[10px] text-gray-400 italic">
                  (edited)
                </span>
              )}
              {c.pinned && (
                <Pin className="h-3 w-3 text-amber-500 fill-amber-500" />
              )}
            </div>

            {isEditing ? (
              <div className="mt-1">
                <textarea
                  value={editMessage}
                  onChange={(e) => setEditMessage(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleEdit(c._id);
                    }
                    if (e.key === "Escape") {
                      setEditingId(null);
                      setEditMessage("");
                    }
                  }}
                  rows={2}
                  className="w-full resize-none rounded-md border border-blue-300 bg-white px-2.5 py-1.5 text-sm text-gray-800 outline-none focus:ring-1 focus:ring-blue-200"
                  autoFocus
                />
                <div className="mt-1 flex gap-1.5">
                  <button
                    onClick={() => handleEdit(c._id)}
                    className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50"
                  >
                    <Check className="h-3 w-3" /> Save
                  </button>
                  <button
                    onClick={() => { setEditingId(null); setEditMessage(""); }}
                    className="flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100"
                  >
                    <X className="h-3 w-3" /> Cancel
                  </button>
                </div>
              </div>
            ) : (
              <p className="mt-0.5 text-sm leading-relaxed text-gray-700 whitespace-pre-wrap">
                {c.message}
              </p>
            )}

            {renderReactions(c)}

            {/* Copied link toast */}
            {copiedLink === c._id && (
              <span className="mt-1 inline-block text-[10px] text-green-600 font-medium">
                Link copied!
              </span>
            )}
          </div>

          {/* Action buttons — show on hover */}
          {!isEditing && (
            <div className="absolute right-0 top-0 hidden items-center gap-0.5 rounded-md border border-gray-200 bg-white px-0.5 py-0.5 shadow-sm group-hover:flex">
              {/* Quick react */}
              <button
                onClick={() =>
                  setReactionPickerFor(
                    reactionPickerFor === c._id ? null : c._id
                  )
                }
                className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                title="React"
              >
                <span className="text-sm">😊</span>
              </button>
              {/* Reply (only for top-level) */}
              {!isReply && (
                <button
                  onClick={() => {
                    setReplyTo(replyTo === c._id ? null : c._id);
                    setOpenMenu(null);
                  }}
                  className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                  title="Reply"
                >
                  <CornerDownRight className="h-3.5 w-3.5" />
                </button>
              )}
              {/* More menu */}
              <button
                onClick={() =>
                  setOpenMenu(openMenu === c._id ? null : c._id)
                }
                className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                title="More"
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>

        {/* Reaction picker */}
        {reactionPickerFor === c._id && (
          <div
            ref={menuRef}
            className="absolute right-0 top-7 z-10 flex gap-1 rounded-lg border border-gray-200 bg-white p-1.5 shadow-lg"
          >
            {REACTION_PALETTE.map((emoji) => (
              <button
                key={emoji}
                onClick={() => handleReact(c._id, emoji)}
                className="rounded p-1 text-base hover:bg-gray-100 transition-transform hover:scale-125"
              >
                {emoji}
              </button>
            ))}
          </div>
        )}

        {/* More menu dropdown */}
        {openMenu === c._id && (
          <div
            ref={menuRef}
            className="absolute right-0 top-7 z-10 w-40 rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
          >
            <button
              onClick={() => handleCopyLink(c._id)}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
            >
              <Link2 className="h-3.5 w-3.5" /> Copy link
            </button>
            <button
              onClick={() => handlePin(c._id, c.pinned)}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
            >
              <Pin className="h-3.5 w-3.5" />
              {c.pinned ? "Unpin" : "Pin comment"}
            </button>
            {isMe && (
              <button
                onClick={() => {
                  setEditingId(c._id);
                  setEditMessage(c.message);
                  setOpenMenu(null);
                }}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
              >
                <Pencil className="h-3.5 w-3.5" /> Edit
              </button>
            )}
          </div>
        )}

        {/* Reply input */}
        {replyTo === c._id && (
          <div className="ml-8 mt-2 flex items-end gap-2">
            <Avatar name={userName} image={userImage} size="sm" />
            <textarea
              value={replyMessage}
              onChange={(e) => setReplyMessage(e.target.value)}
              onKeyDown={(e) => handleKeyDown(e, c._id)}
              placeholder={`Reply to ${c.user_name}...`}
              rows={1}
              className="flex-1 resize-none rounded-md border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-sm text-gray-800 placeholder:text-gray-400 outline-none focus:border-blue-400 focus:bg-white focus:ring-1 focus:ring-blue-200"
              autoFocus
            />
            <button
              onClick={() => handleSend(c._id)}
              disabled={!replyMessage.trim() || sending}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-blue-600 text-white disabled:opacity-40"
            >
              {sending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Send className="h-3 w-3" />
              )}
            </button>
            <button
              onClick={() => { setReplyTo(null); setReplyMessage(""); }}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-gray-400 hover:bg-gray-100"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {/* Threaded replies */}
        {!isReply && repliesMap[c._id] && repliesMap[c._id].length > 0 && (
          <div className="mt-2 space-y-2 border-l-2 border-gray-100 pl-2">
            {repliesMap[c._id].map((reply) =>
              renderCommentBubble(reply, true)
            )}
          </div>
        )}
      </div>
    );
  };

  /* ── Render ────────────────────────────────────────────────────── */

  return (
    <div className="flex flex-col">
      {/* Comment list */}
      <div className="max-h-80 overflow-y-auto px-5 py-3">
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-6 text-sm text-gray-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading...
          </div>
        ) : comments.length === 0 ? (
          <div className="flex flex-col items-center gap-1.5 py-8 text-center">
            <MessageSquare className="h-8 w-8 text-gray-200" />
            <p className="text-sm font-medium text-gray-400">
              No comments yet
            </p>
            <p className="text-xs text-gray-300">
              Start the discussion — tag your teammates
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {/* Pinned section */}
            {pinnedComments.length > 0 && (
              <div className="mb-4">
                <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-amber-600">
                  <Pin className="h-3 w-3 fill-amber-500" />
                  Pinned
                </div>
                <div className="space-y-3 rounded-lg bg-amber-50/50 p-2">
                  {pinnedComments.map((c) => renderCommentBubble(c))}
                </div>
              </div>
            )}

            {/* All other comments */}
            {unpinnedComments.map((c) => renderCommentBubble(c))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Main input */}
      <div className="border-t border-gray-100 px-5 py-3">
        <div className="flex items-end gap-2">
          <div className="mt-1 shrink-0">
            <Avatar name={userName} image={userImage} size="md" />
          </div>
          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => handleKeyDown(e)}
            placeholder="Add a comment..."
            rows={1}
            className="flex-1 resize-none rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-800 placeholder:text-gray-400 outline-none transition-colors focus:border-blue-400 focus:bg-white focus:ring-1 focus:ring-blue-200"
          />
          <button
            onClick={() => handleSend()}
            disabled={!message.trim() || sending}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
          >
            {sending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        </div>
        <p className="mt-1.5 pl-9 text-[10px] text-gray-400">
          Enter to send &middot; Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
