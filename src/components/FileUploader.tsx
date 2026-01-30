'use client'

import { useState, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'

// Supported file types matching the backend
const SUPPORTED_TYPES = {
  'application/pdf': 'PDF',
  'text/csv': 'CSV',
  'application/vnd.ms-excel': 'Excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel',
  'image/jpeg': 'Image',
  'image/png': 'Image',
  'image/gif': 'Image',
  'image/webp': 'Image',
  'text/plain': 'Text',
  'application/json': 'JSON',
}

const ACCEPT_STRING = Object.keys(SUPPORTED_TYPES).join(',')

interface UploadResult {
  success: boolean
  message: string
  file_name: string
  file_size: number
  mime_type: string
  storage_path: string | null
  extracted_text_preview: string
  extracted_text_length: number
  ingestion_status: string
}

interface FileUploaderProps {
  userId?: string
}

export function FileUploader({ userId = '00000000-0000-0000-0000-000000000001' }: FileUploaderProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<UploadResult | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const router = useRouter()

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }, [])

  const uploadFile = async (file: File) => {
    // Validate file type
    if (!Object.keys(SUPPORTED_TYPES).includes(file.type)) {
      setError(`Unsupported file type: ${file.type}. Supported: PDF, CSV, Excel, Images, Text, JSON`)
      return
    }

    // Validate file size (50MB max)
    const maxSize = 50 * 1024 * 1024
    if (file.size > maxSize) {
      setError(`File too large: ${(file.size / 1024 / 1024).toFixed(2)}MB. Maximum: 50MB`)
      return
    }

    setIsUploading(true)
    setError(null)
    setSuccess(null)
    setUploadProgress('Uploading file...')

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('user_id', userId)
      formData.append('source', 'dashboard_upload')

      setUploadProgress('Parsing file content...')

      // Use Next.js API proxy to keep API key secure on server side
      const response = await fetch('/api/memory/upload', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `Upload failed: ${response.status}`)
      }

      const result: UploadResult = await response.json()

      setUploadProgress('Ingesting into memory...')

      // Short delay to show ingestion status
      await new Promise(resolve => setTimeout(resolve, 1000))

      setSuccess(result)
      setUploadProgress('')

      // Refresh the page to show new memories
      router.refresh()

    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
      setUploadProgress('')
    } finally {
      setIsUploading(false)
    }
  }

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)

    const files = e.dataTransfer.files
    if (files.length > 0) {
      uploadFile(files[0])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      uploadFile(files[0])
    }
    // Reset input so same file can be selected again
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleClick = () => {
    fileInputRef.current?.click()
  }

  const dismissSuccess = () => {
    setSuccess(null)
  }

  return (
    <div className="mb-8">
      {/* Success Toast */}
      {success && (
        <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded-lg">
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-3">
              <svg className="w-5 h-5 text-green-600 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div>
                <h4 className="text-sm font-medium text-green-800">File Uploaded Successfully</h4>
                <p className="text-sm text-green-700 mt-1">
                  <strong>{success.file_name}</strong> ({(success.file_size / 1024).toFixed(1)} KB)
                </p>
                <p className="text-xs text-green-600 mt-1">
                  Extracted {success.extracted_text_length.toLocaleString()} characters - {success.ingestion_status}
                </p>
                {success.extracted_text_preview && (
                  <details className="mt-2">
                    <summary className="text-xs text-green-600 cursor-pointer hover:text-green-800">
                      Preview extracted text
                    </summary>
                    <pre className="mt-2 p-2 bg-white rounded text-xs text-gray-700 whitespace-pre-wrap max-h-32 overflow-y-auto">
                      {success.extracted_text_preview}
                    </pre>
                  </details>
                )}
              </div>
            </div>
            <button
              onClick={dismissSuccess}
              className="text-green-600 hover:text-green-800"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
      )}

      {/* Error Toast */}
      {error && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg">
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-red-600 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div className="flex-1">
              <h4 className="text-sm font-medium text-red-800">Upload Failed</h4>
              <p className="text-sm text-red-700 mt-1">{error}</p>
            </div>
            <button
              onClick={() => setError(null)}
              className="text-red-600 hover:text-red-800"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
      )}

      {/* Drop Zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        className={`
          relative border-2 border-dashed rounded-lg p-8
          transition-all cursor-pointer
          ${isDragging
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-300 bg-gray-50 hover:border-gray-400 hover:bg-gray-100'
          }
          ${isUploading ? 'pointer-events-none opacity-75' : ''}
        `}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPT_STRING}
          onChange={handleFileSelect}
          className="hidden"
        />

        <div className="text-center">
          {isUploading ? (
            <>
              <div className="mx-auto w-12 h-12 mb-4">
                <svg className="animate-spin w-full h-full text-blue-600" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
              </div>
              <p className="text-sm font-medium text-blue-600">{uploadProgress}</p>
              <p className="text-xs text-gray-500 mt-1">This may take a moment for images (OCR processing)</p>
            </>
          ) : (
            <>
              <svg
                className={`mx-auto w-12 h-12 mb-4 ${isDragging ? 'text-blue-500' : 'text-gray-400'}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                />
              </svg>
              <p className="text-sm font-medium text-gray-700">
                {isDragging ? 'Drop file here' : 'Drag & drop a file, or click to browse'}
              </p>
              <p className="text-xs text-gray-500 mt-2">
                Supported: PDF, CSV, Excel, Images (JPG, PNG, GIF, WebP), Text, JSON
              </p>
              <p className="text-xs text-gray-400 mt-1">
                Max file size: 50MB
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
