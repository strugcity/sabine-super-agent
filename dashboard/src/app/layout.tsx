import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'The Gantry - God View Dashboard',
  description: 'Real-time monitoring for Strug City Engineering Office',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} bg-gantry-dark text-white antialiased`}>
        {children}
      </body>
    </html>
  )
}
