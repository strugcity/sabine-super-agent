import { Entity } from '@/lib/types/database';

interface EntityCardProps {
  entity: Entity;
}

const domainColors = {
  work: 'bg-blue-50 border-blue-200 text-blue-700',
  family: 'bg-pink-50 border-pink-200 text-pink-700',
  personal: 'bg-purple-50 border-purple-200 text-purple-700',
  logistics: 'bg-green-50 border-green-200 text-green-700',
};

const domainBadgeColors = {
  work: 'bg-blue-100 text-blue-800',
  family: 'bg-pink-100 text-pink-800',
  personal: 'bg-purple-100 text-purple-800',
  logistics: 'bg-green-100 text-green-800',
};

export function EntityCard({ entity }: EntityCardProps) {
  // Format attributes for display (show first 3 keys or truncate if large)
  const attributesPreview = (() => {
    const keys = Object.keys(entity.attributes);
    if (keys.length === 0) return 'No attributes';
    
    const preview = keys.slice(0, 3).map(key => {
      const value = entity.attributes[key];
      const displayValue = typeof value === 'string' && value.length > 50 
        ? `${value.substring(0, 50)}...` 
        : String(value);
      return `${key}: ${displayValue}`;
    });
    
    if (keys.length > 3) {
      preview.push(`... +${keys.length - 3} more`);
    }
    
    return preview.join(', ');
  })();

  return (
    <div className={`border-2 rounded-lg p-4 transition-all hover:shadow-md ${domainColors[entity.domain]}`}>
      <div className="flex items-start justify-between mb-2">
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-gray-900 mb-1">
            {entity.name}
          </h3>
          <div className="flex items-center gap-2 mb-2">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${domainBadgeColors[entity.domain]}`}>
              {entity.domain}
            </span>
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
              {entity.type}
            </span>
            {entity.status !== 'active' && (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-200 text-gray-600">
                {entity.status}
              </span>
            )}
          </div>
        </div>
      </div>
      
      <div className="text-sm text-gray-600 mb-2">
        <span className="font-medium">Attributes:</span>
        <div className="mt-1 text-xs font-mono bg-white/50 rounded p-2 break-words">
          {attributesPreview}
        </div>
      </div>
      
      <div className="text-xs text-gray-500 mt-3">
        Created: {new Date(entity.created_at).toLocaleDateString()}
      </div>
    </div>
  );
}
