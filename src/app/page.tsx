import Link from 'next/link';

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <div className="text-center">
        <h1 className="text-4xl font-bold mb-4">
          Personal Super Agent V1
        </h1>
        <p className="text-xl text-gray-600 mb-8">
          Family logistics, complex tasks, and deep context management
        </p>
        <div className="flex gap-4 justify-center">
          <Link
            href="/overview"
            className="px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors"
          >
            📊 Overview Dashboard
          </Link>
          <Link
            href="/dashboard/memory"
            className="px-6 py-3 bg-green-600 text-white font-medium rounded-lg hover:bg-green-700 transition-colors"
          >
            🧠 Memory Dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}