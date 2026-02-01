/**
 * ThemeProvider - Dark Mode Support for Project Sabine
 *
 * GOVERNANCE: This component is UI-only (Project Sabine frontend).
 * It does NOT access personal data or backend logic.
 * Compliant with Strug City Constitution Section II.
 */
'use client'

import { ThemeProvider as NextThemesProvider } from 'next-themes'
import { type ThemeProviderProps } from 'next-themes'

export function ThemeProvider({ children, ...props }: ThemeProviderProps) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      {...props}
    >
      {children}
    </NextThemesProvider>
  )
}
