import { type ReactNode, type ButtonHTMLAttributes, forwardRef } from 'react'
import { cn } from '../lib/cn'
import { haptic } from '../lib/telegram'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'md' | 'sm'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  block?: boolean
  loading?: boolean
  hapticFeedback?: boolean
  children?: ReactNode
}

/**
 * Buttons trigger Telegram haptics by default — on a Mini App that is the
 * cheapest way to make a UI feel native.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', block, loading, hapticFeedback = true, className, disabled, onClick, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        'btn',
        `btn--${variant}`,
        size === 'sm' && 'btn--sm',
        block && 'btn--block',
        className,
      )}
      disabled={disabled || loading}
      onClick={(event) => {
        if (hapticFeedback) haptic('light')
        onClick?.(event)
      }}
      {...rest}
    >
      {loading && <span className="spinner" aria-hidden />}
      {children}
    </button>
  )
})
