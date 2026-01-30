import { createClient } from '@/lib/supabase/server';
import { EntityCard } from '@/components/EntityCard';
import { MemoryStream } from '@/components/MemoryStream';
import { DashboardHeader } from '@/components/DashboardHeader';
import { FileUploader } from '@/components/FileUploader';
import { Entity, Memory, DomainEnum, EntitiesByDomain } from '@/lib/types/database';

async function getEntities(): Promise<EntitiesByDomain> {
  const supabase = await createClient();
  
  const { data, error } = await supabase
    .from('entities')
    .select('*')
    .eq('status', 'active')
    .order('created_at', { ascending: false });

  if (error) {
    console.error('Error fetching entities:', error);
    return { work: [], family: [], personal: [], logistics: [] };
  }

  // Group entities by domain
  const grouped: EntitiesByDomain = {
    work: [],
    family: [],
    personal: [],
    logistics: [],
  };

  (data as Entity[]).forEach((entity) => {
    grouped[entity.domain].push(entity);
  });

  return grouped;
}

async function getMemories(): Promise<Memory[]> {
  const supabase = await createClient();
  
  const { data, error } = await supabase
    .from('memories')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(50); // Limit to 50 most recent memories

  if (error) {
    console.error('Error fetching memories:', error);
    return [];
  }

  return (data as Memory[]) || [];
}

const domainLabels: Record<DomainEnum, { name: string; emoji: string }> = {
  work: { name: 'Work', emoji: '💼' },
  family: { name: 'Family', emoji: '👨‍👩‍👧‍👦' },
  personal: { name: 'Personal', emoji: '🧘' },
  logistics: { name: 'Logistics', emoji: '📦' },
};

export default async function MemoryDashboard() {
  const [entities, memories] = await Promise.all([
    getEntities(),
    getMemories(),
  ]);

  const totalEntities = Object.values(entities).reduce(
    (sum, domainEntities) => sum + domainEntities.length,
    0
  );

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header with New Entity button */}
      <DashboardHeader
        totalEntities={totalEntities}
        totalMemories={memories.length}
      />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Knowledge Upload Section */}
        <section className="mb-8">
          <h2 className="text-2xl font-bold text-gray-900 mb-4">
            Upload Knowledge
          </h2>
          <p className="text-sm text-gray-600 mb-4">
            Upload files to extract and ingest knowledge into the Context Engine.
          </p>
          <FileUploader />
        </section>

        {/* Entities Section */}
        <section className="mb-12">
          <h2 className="text-2xl font-bold text-gray-900 mb-6">
            Entities by Domain
          </h2>

          {totalEntities === 0 ? (
            <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
              <p className="text-lg text-gray-500">No entities found</p>
              <p className="text-sm text-gray-400 mt-2">
                Entities will appear here as they are created
              </p>
            </div>
          ) : (
            <div className="space-y-8">
              {(Object.keys(entities) as DomainEnum[]).map((domain) => {
                const domainEntities = entities[domain];
                
                if (domainEntities.length === 0) return null;

                return (
                  <div key={domain}>
                    <h3 className="text-xl font-semibold text-gray-800 mb-4 flex items-center gap-2">
                      <span>{domainLabels[domain].emoji}</span>
                      <span>{domainLabels[domain].name}</span>
                      <span className="text-sm font-normal text-gray-500">
                        ({domainEntities.length})
                      </span>
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {domainEntities.map((entity) => (
                        <EntityCard key={entity.id} entity={entity} />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Memories Section */}
        <section>
          <h2 className="text-2xl font-bold text-gray-900 mb-6">
            Memory Stream
          </h2>
          <MemoryStream memories={memories} />
        </section>
      </main>
    </div>
  );
}
