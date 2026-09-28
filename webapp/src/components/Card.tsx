import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../lib/cn'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  hero?: boolean
  flat?: boolean
}

export function Card({ children, className, hero, flat, ...rest }: CardProps) {
  return (
    <div className={cn('card', hero && 'card--hero', flat && 'card--flat', className)} {...rest}>
      {children}
    </div>
  )
}

export function SectionTitle({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="section-title">
      <h2>{title}</h2>
      {action}
    </div>
  )
}
