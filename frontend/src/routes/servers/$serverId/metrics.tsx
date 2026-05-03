import { createFileRoute, Link } from '@tanstack/react-router';
import { motion } from 'framer-motion';
import { ArrowLeft, Activity, Clock } from 'lucide-react';
import { ResourceTimeline } from '../../../components/charts/resource-timeline';
import { useServers } from '../../../hooks/use-servers';
import { formatDate } from '../../../lib/utils';
import { springs } from '../../../lib/animations';

export const Route = createFileRoute('/servers/$serverId/metrics')({
  component: ServerMetricsPage,
});

function ServerMetricsPage() {
  const { serverId } = Route.useParams();
  const { data: servers = [] } = useServers();

  const server = servers.find((s) => s.id === serverId);

  // Build timeline from server lifecycle events
  const timelineResources = [
    {
      name: server?.name || 'Server',
      events: [
        {
          start: server?.created_at || new Date().toISOString(),
          end: server?.started_at || new Date().toISOString(),
          status: 'pending',
        },
        ...(server?.status === 'running' && server?.started_at
          ? [
              {
                start: server.started_at,
                end: new Date().toISOString(),
                status: 'running' as const,
              },
            ]
          : []),
        ...(server?.status === 'stopped' && server?.started_at
          ? [
              {
                start: server.started_at,
                end: new Date().toISOString(),
                status: 'stopped' as const,
              },
            ]
          : []),
      ],
    },
  ];

  if (!server) {
    return (
      <div className="p-10 text-center"
      >
        <h2 className="text-lg font-semibold mb-2"
        >Server not found</h2>
        <Link
          to="/servers"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Servers
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8"
    >
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="flex items-center gap-4"
      >
        <Link
          to="/servers/$serverId"
          params={{ serverId }}
          className="p-2 rounded-lg hover:bg-accent transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold"
          >{server.name} — Metrics</h1>
          <p className="text-sm text-muted-foreground"
          >Resource timeline and historical metrics</p>
        </div>
      </motion.div>

      {/* Resource Timeline */}
      <motion.div
        className="bubble p-5"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1, ...springs.gentle }}
      >
        <div className="flex items-center justify-between mb-4"
        >
          <h3 className="text-sm font-semibold"
          >Server Lifecycle Timeline</h3>
          <Clock className="w-4 h-4 text-muted-foreground" />
        </div>
        <ResourceTimeline resources={timelineResources} height={120} />
      </motion.div>

      {/* Historical Stats */}
      <motion.div
        className="bubble p-5"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2, ...springs.gentle }}
      >
        <div className="flex items-center justify-between mb-4"
        >
          <h3 className="text-sm font-semibold"
          >Server Information</h3>
          <Activity className="w-4 h-4 text-muted-foreground" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4"
        >
          <div className="space-y-3"
          >
            <div className="flex justify-between text-sm"
            >
              <span className="text-muted-foreground"
              >Server ID</span>
              <span className="font-mono text-xs"
              >{server.id}</span>
            </div>
            <div className="flex justify-between text-sm"
            >
              <span className="text-muted-foreground"
              >Created</span>
              <span
              >{formatDate(server.created_at || '')}</span>
            </div>
            {server.started_at && (
              <div className="flex justify-between text-sm"
              >
                <span className="text-muted-foreground"
                >Last Started</span>
                <span
                >{formatDate(server.started_at || '')}</span>
              </div>
            )}
          </div>
          <div className="space-y-3"
          >
            {server.allocated_cpu !== undefined && (
              <div className="flex justify-between text-sm"
              >
                <span className="text-muted-foreground"
                >Allocated CPU</span>
                <span className="font-mono"
                >{server.allocated_cpu} cores</span>
              </div>
            )}
            {server.allocated_memory !== undefined && (
              <div className="flex justify-between text-sm"
              >
                <span className="text-muted-foreground"
                >Allocated Memory</span>
                <span className="font-mono"
                >{server.allocated_memory} GB</span>
              </div>
            )}
            {server.external_url && (
              <div className="flex justify-between text-sm"
              >
                <span className="text-muted-foreground"
                >External URL</span>
                <a
                  href={server.external_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline truncate max-w-[200px]"
                >
                  {server.external_url}
                </a>
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
