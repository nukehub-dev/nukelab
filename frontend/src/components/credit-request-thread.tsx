// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import { Lock, MessageSquare, Send } from 'lucide-react'
import { Textarea } from './ui/textarea'
import { Button } from './ui/button'
import { useCreditRequestMessages, useAddCreditRequestMessage } from '../hooks/use-credit-requests'
import { cn, formatRelativeTime } from '../lib/utils'

const MAX_MESSAGE_LENGTH = 2000

interface CreditRequestThreadProps {
  requestId: string
  /** Whether the reply box is shown (only open requests accept messages). */
  canReply: boolean
  /** Hint shown next to the send button, e.g. which status change replying triggers. */
  replyHint: string
  replyPlaceholder?: string
  /** Reviewers only: show a Reply / Internal note toggle on the reply box. */
  allowInternal?: boolean
}

/** Conversation thread for a credit request: admin messages left, requester right. */
export function CreditRequestThread({
  requestId,
  canReply,
  replyHint,
  replyPlaceholder,
  allowInternal = false,
}: CreditRequestThreadProps) {
  const { data, isLoading } = useCreditRequestMessages(requestId)
  const addMessage = useAddCreditRequestMessage()
  const [body, setBody] = useState('')
  const [internal, setInternal] = useState(false)

  const messages = data?.messages || []
  const trimmed = body.trim()

  const handleSend = () => {
    if (!trimmed || trimmed.length > MAX_MESSAGE_LENGTH) return
    addMessage.mutate(
      { requestId, body: trimmed, internal: internal || undefined },
      { onSuccess: () => setBody('') }
    )
  }

  return (
    <div className="space-y-3">
      <div className="max-h-64 overflow-y-auto space-y-2 pr-1">
        {isLoading ? (
          <div className="space-y-2 animate-pulse">
            {[1, 2].map((i) => (
              <div key={i} className="h-12 w-3/4 bg-muted rounded-xl" />
            ))}
          </div>
        ) : messages.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-4">No messages yet</p>
        ) : (
          messages.map((msg) => {
            const isInternalNote = msg.is_admin && msg.is_internal
            return (
              <div
                key={msg.id}
                className={cn('flex', msg.is_admin ? 'justify-start' : 'justify-end')}
              >
                <div
                  className={cn(
                    'max-w-[85%] rounded-xl px-3 py-2 space-y-1 border',
                    isInternalNote
                      ? 'bg-amber-500/5 border-amber-500/30 border-dashed'
                      : msg.is_admin
                        ? 'bg-muted/60 border-border/50'
                        : 'bg-primary/10 border-primary/20'
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-medium">
                      {msg.author_username}
                      {msg.is_admin && <span className="text-muted-foreground"> (admin)</span>}
                    </span>
                    {isInternalNote && (
                      <span className="inline-flex items-center gap-0.5 text-[9px] px-1 py-0.5 rounded bg-amber-500/10 text-amber-400 font-medium">
                        <Lock className="w-2.5 h-2.5" />
                        Internal
                      </span>
                    )}
                    <span className="text-[10px] text-muted-foreground">
                      {formatRelativeTime(msg.created_at)}
                    </span>
                  </div>
                  <p className="text-sm whitespace-pre-wrap break-words">{msg.body}</p>
                </div>
              </div>
            )
          })
        )}
      </div>

      {canReply && (
        <div className="space-y-2">
          {allowInternal && (
            <div className="flex gap-2 p-1 bg-muted rounded-xl">
              <button
                type="button"
                onClick={() => setInternal(false)}
                className={cn(
                  'flex-1 flex items-center justify-center gap-2 px-4 py-1.5 rounded-lg text-xs font-medium transition-all',
                  !internal
                    ? 'bg-primary/10 border-primary/30 text-primary shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <MessageSquare className="w-3.5 h-3.5" />
                Reply
              </button>
              <button
                type="button"
                onClick={() => setInternal(true)}
                className={cn(
                  'flex-1 flex items-center justify-center gap-2 px-4 py-1.5 rounded-lg text-xs font-medium transition-all',
                  internal
                    ? 'bg-amber-500/10 border-amber-500/30 text-amber-400 shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <Lock className="w-3.5 h-3.5" />
                Internal note
              </button>
            </div>
          )}
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder={
              internal ? 'Internal note for reviewers…' : (replyPlaceholder ?? 'Write a reply…')
            }
            maxLength={MAX_MESSAGE_LENGTH}
            rows={3}
            disabled={addMessage.isPending}
            data-testid="credit-request-reply-input"
          />
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              {internal ? 'Internal notes are not visible to the requester.' : replyHint}
            </p>
            <Button
              type="button"
              size="sm"
              className="gap-1.5 shrink-0"
              onClick={handleSend}
              loading={addMessage.isPending}
              disabled={!trimmed || trimmed.length > MAX_MESSAGE_LENGTH}
              data-testid="credit-request-reply-send"
            >
              <Send className="w-3.5 h-3.5" />
              Send
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
