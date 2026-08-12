// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import { Send } from 'lucide-react'
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
}

/** Conversation thread for a credit request: admin messages left, requester right. */
export function CreditRequestThread({
  requestId,
  canReply,
  replyHint,
  replyPlaceholder,
}: CreditRequestThreadProps) {
  const { data, isLoading } = useCreditRequestMessages(requestId)
  const addMessage = useAddCreditRequestMessage()
  const [body, setBody] = useState('')

  const messages = data?.messages || []
  const trimmed = body.trim()

  const handleSend = () => {
    if (!trimmed || trimmed.length > MAX_MESSAGE_LENGTH) return
    addMessage.mutate({ requestId, body: trimmed }, { onSuccess: () => setBody('') })
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
          messages.map((msg) => (
            <div
              key={msg.id}
              className={cn('flex', msg.is_admin ? 'justify-start' : 'justify-end')}
            >
              <div
                className={cn(
                  'max-w-[85%] rounded-xl px-3 py-2 space-y-1 border',
                  msg.is_admin ? 'bg-muted/60 border-border/50' : 'bg-primary/10 border-primary/20'
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-medium">
                    {msg.author_username}
                    {msg.is_admin && <span className="text-muted-foreground"> (admin)</span>}
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    {formatRelativeTime(msg.created_at)}
                  </span>
                </div>
                <p className="text-sm whitespace-pre-wrap break-words">{msg.body}</p>
              </div>
            </div>
          ))
        )}
      </div>

      {canReply && (
        <div className="space-y-2">
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder={replyPlaceholder ?? 'Write a reply…'}
            maxLength={MAX_MESSAGE_LENGTH}
            rows={3}
            disabled={addMessage.isPending}
            data-testid="credit-request-reply-input"
          />
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">{replyHint}</p>
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
