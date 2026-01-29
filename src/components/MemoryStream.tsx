import { Memory } from '@/lib/types/database';

interface MemoryStreamProps {
  memories: Memory[];
}

export function MemoryStream({ memories }: MemoryStreamProps) {
  if (memories.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p className="text-lg">No memories found</p>
        <p className="text-sm mt-2">Memories will appear here as they are created</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {memories.map((memory) => (
        <MemoryCard key={memory.id} memory={memory} />
      ))}
    </div>
  );
}

function MemoryCard({ memory }: { memory: Memory }) {
  const formattedDate = new Date(memory.created_at).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  // Calculate importance color
  const getImportanceColor = (score: number) => {
    if (score >= 0.8) return 'bg-red-100 text-red-800';
    if (score >= 0.6) return 'bg-orange-100 text-orange-800';
    if (score >= 0.4) return 'bg-yellow-100 text-yellow-800';
    return 'bg-gray-100 text-gray-800';
  };

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center px-2 py-1 rounded text-xs font-medium ${getImportanceColor(memory.importance_score)}`}>
            Importance: {(memory.importance_score * 100).toFixed(0)}%
          </span>
          {memory.entity_links && memory.entity_links.length > 0 && (
            <span className="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-blue-100 text-blue-800">
              🔗 {memory.entity_links.length} {memory.entity_links.length === 1 ? 'entity' : 'entities'}
            </span>
          )}
        </div>
        <span className="text-xs text-gray-500">{formattedDate}</span>
      </div>

      <div className="text-gray-800 mb-3 leading-relaxed">
        {memory.content}
      </div>

      {memory.metadata && Object.keys(memory.metadata).length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          <details className="text-xs text-gray-600">
            <summary className="cursor-pointer font-medium text-gray-700 hover:text-gray-900">
              View metadata
            </summary>
            <pre className="mt-2 p-2 bg-gray-50 rounded overflow-x-auto">
              {JSON.stringify(memory.metadata, null, 2)}
            </pre>
          </details>
        </div>
      )}

      {memory.entity_links && memory.entity_links.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-100">
          <span className="text-xs font-medium text-gray-700">Entity Links:</span>
          <div className="mt-1 flex flex-wrap gap-1">
            {memory.entity_links.map((entityId) => (
              <span
                key={entityId}
                className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-gray-100 text-gray-600"
                title={entityId}
              >
                {entityId.substring(0, 8)}...
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
