"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { MessageSquare, Send, User } from "lucide-react";

interface Comment {
  _id: string;
  grant_id: string;
  user_name: string;
  message: string;
  created_at: string;
}

interface CommentThreadProps {
  grantId: string;
}

/** Return a human-friendly relative timestamp, e.g. "3 min ago". */
function timeAgo(iso: string): string {
  const seconds = Math.floor(
    (Date.now() - new Date(iso).getTime()) / 1000
  );
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

const LS_KEY = "altcarbon_comment_username";

export function CommentThread({ grantId }: CommentThreadProps) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [userName, setUserName] = useState("Team Member");
  const bottomRef = useRef<HTMLDivElement>(null);

  // Restore saved user name from localStorage
  useEffect(() => {
    const saved = localStorage.getItem(LS_KEY);
    if (saved) setUserName(saved);
  }, []);

  // Persist user name changes
  const handleNameChange = (name: string) => {
    setUserName(name);
    localStorage.setItem(LS_KEY, name);
  };

  const fetchComments = useCallback(async () => {
    try {
      const res = await fetch(`/api/grants/${grantId}/comments`);
      if (!res.ok) throw new Error("Failed to fetch comments");
      const data: Comment[] = await res.json();
      setComments(data);
    } catch {
      // Silently fail — the empty state handles no-data gracefully
    } finally {
      setLoading(false);
    }
  }, [grantId]);

  // Fetch on mount and when grantId changes
  useEffect(() => {
    setLoading(true);
    fetchComments();
  }, [fetchComments]);

  // Scroll to bottom when new comments arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [comments]);

  const handleSend = async () => {
    const trimmed = message.trim();
    if (!trimmed || sending) return;

    setSending(true);
    try {
      const res = await fetch(`/api/grants/${grantId}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_name: userName || "Team Member",
          message: trimmed,
        }),
      });
      if (!res.ok) throw new Error("Failed to post comment");
      setMessage("");
      await fetchComments();
    } catch {
      // Could add toast here later
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 px-5 py-3">
        <MessageSquare className="h-4 w-4 text-gray-500" />
        <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">
          Comments
        </span>
        {comments.length > 0 && (
          <span className="rounded-full bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-600">
            {comments.length}
          </span>
        )}
      </div>

      {/* Comment list */}
      <div className="max-h-72 overflow-y-auto px-5">
        {loading ? (
          <p className="py-4 text-center text-sm text-gray-400">
            Loading comments...
          </p>
        ) : comments.length === 0 ? (
          <div className="flex flex-col items-center gap-1 py-6 text-center">
            <MessageSquare className="h-8 w-8 text-gray-300" />
            <p className="text-sm text-gray-400">
              No comments yet. Start the discussion!
            </p>
          </div>
        ) : (
          <div className="space-y-3 pb-2">
            {comments.map((c) => (
              <div key={c._id} className="rounded-lg bg-gray-50 px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-100">
                    <User className="h-3 w-3 text-blue-600" />
                  </div>
                  <span className="text-xs font-semibold text-gray-800">
                    {c.user_name}
                  </span>
                  <span className="text-xs text-gray-400">
                    {timeAgo(c.created_at)}
                  </span>
                </div>
                <p className="mt-1 pl-7 text-sm leading-relaxed text-gray-700">
                  {c.message}
                </p>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-gray-100 px-5 py-3">
        {/* Name row */}
        <div className="mb-2 flex items-center gap-2">
          <User className="h-3.5 w-3.5 text-gray-400" />
          <input
            type="text"
            value={userName}
            onChange={(e) => handleNameChange(e.target.value)}
            placeholder="Your name"
            className="w-36 border-b border-dashed border-gray-300 bg-transparent text-xs text-gray-600 outline-none focus:border-blue-400"
          />
        </div>

        {/* Message row */}
        <div className="flex items-end gap-2">
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Add a comment..."
            rows={1}
            className="flex-1 resize-none rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800 placeholder:text-gray-400 outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
          />
          <button
            onClick={handleSend}
            disabled={!message.trim() || sending}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
