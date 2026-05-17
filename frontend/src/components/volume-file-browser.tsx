import { useState, useMemo, useRef, useCallback } from 'react';
import { useToastStore } from '../stores/toast-store';
import { 
  Folder, 
  File, 
  ArrowUp, 
  Trash2, 
  Download, 
  X, 
  HardDrive, 
  Search, 
  ChevronLeft,
  ChevronRight,
  ArrowUpDown,
  ArrowUp as ArrowUpIcon,
  ArrowDown,
  Loader2
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useVolumeFiles, useDeleteVolumeFile } from '../hooks/use-volumes';
import { api } from '../lib/api';
import { formatBytes } from '../lib/utils';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Tooltip } from './ui/tooltip';
import { useConfirmDialog } from './ui/confirm-dialog';
import { useToast } from '../stores/toast-store';

interface FileBrowserProps {
  volumeId: string;
  volumeName: string;
  onClose: () => void;
}

const PAGE_SIZE = 100;

export function FileBrowser({ volumeId, volumeName, onClose }: FileBrowserProps) {
  const [currentPath, setCurrentPath] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [sortBy, setSortBy] = useState<'name' | 'size' | 'modified'>('name');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(1);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const params = useMemo(() => ({
    path: currentPath,
    search: debouncedSearch || undefined,
    sort_by: sortBy,
    sort_order: sortOrder,
    page,
    page_size: PAGE_SIZE,
  }), [currentPath, debouncedSearch, sortBy, sortOrder, page]);

  const { data, isLoading, error } = useVolumeFiles(volumeId, params);
  const deleteFile = useDeleteVolumeFile();
  const { confirm, dialog } = useConfirmDialog();
  const { error: toastError } = useToast();
  const [deleting, setDeleting] = useState<string | null>(null);
  const [scrolledItems, setScrolledItems] = useState(50); // Virtual scrolling window

  // Handle search with debounce
  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
    setPage(1); // Reset to first page on search
    
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    searchTimeoutRef.current = setTimeout(() => {
      setDebouncedSearch(value);
    }, 300);
  };

  const handleNavigate = (itemName: string) => {
    const newPath = currentPath ? `${currentPath}/${itemName}` : itemName;
    setCurrentPath(newPath);
    setPage(1);
    setSearchQuery('');
    setDebouncedSearch('');
    setScrolledItems(50);
  };

  const handleGoUp = () => {
    const parts = currentPath.split('/').filter(Boolean);
    parts.pop();
    setCurrentPath(parts.join('/'));
    setPage(1);
    setScrolledItems(50);
  };

  const handlePathClick = (pathIndex: number) => {
    const parts = currentPath.split('/').filter(Boolean);
    const newPath = parts.slice(0, pathIndex + 1).join('/');
    setCurrentPath(newPath);
    setPage(1);
    setScrolledItems(50);
  };

  const handleDelete = async (itemName: string, itemType: string) => {
    const path = currentPath ? `${currentPath}/${itemName}` : itemName;
    const confirmed = await confirm({
      title: `Delete ${itemType === 'directory' ? 'Folder' : 'File'}`,
      description: `Are you sure you want to delete "${itemName}"? This action cannot be undone.`,
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
      variant: 'danger',
    });
    if (!confirmed) return;

    setDeleting(itemName);
    try {
      await deleteFile.mutateAsync({ volumeId, path });
    } catch (err: any) {
      const message = err?.response?.data?.detail || err.message || 'Failed to delete';
      toastError('Delete Failed', message);
    } finally {
      setDeleting(null);
    }
  };

  const handleDownload = async (itemName: string) => {
    const path = currentPath ? `${currentPath}/${itemName}` : itemName;
    try {
      await api.download(`/volumes/${volumeId}/download?path=${encodeURIComponent(path)}`, itemName);
    } catch (e) {
      useToastStore.getState().addToast({ type: 'error', title: 'Download failed', message: e instanceof Error ? e.message : 'Unknown error', duration: 8000 });
    }
  };

  const handleSort = (column: 'name' | 'size' | 'modified') => {
    if (sortBy === column) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(column);
      setSortOrder('asc');
    }
    setPage(1);
  };

  // Breadcrumb parts
  const breadcrumbParts = useMemo(() => {
    if (!currentPath) return [];
    return currentPath.split('/').filter(Boolean);
  }, [currentPath]);

  // Virtual scroll handler
  const listRef = useRef<HTMLDivElement>(null);
  const handleScroll = useCallback(() => {
    if (!listRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = listRef.current;
    if (scrollTop + clientHeight >= scrollHeight - 200) {
      setScrolledItems(prev => Math.min(prev + 50, data?.items.length || 0));
    }
  }, [data?.items.length]);

  const visibleItems = data?.items.slice(0, scrolledItems) || [];
  const hasMore = scrolledItems < (data?.items.length || 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        className="w-full max-w-4xl max-h-[85vh] rounded-2xl bg-card/95 backdrop-blur-xl border border-border/50 shadow-2xl overflow-hidden flex flex-col"
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.9, opacity: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="h-1 bg-primary" />
        <div className="p-4 border-b border-border/50 space-y-3">
          {/* Title row */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <HardDrive className="w-5 h-5 text-primary shrink-0" />
              <div className="min-w-0">
                <h3 className="font-semibold truncate">{volumeName}</h3>
              </div>
            </div>
            <Button variant="ghost" size="sm" onClick={onClose}>
              <X className="w-4 h-4" />
            </Button>
          </div>

          {/* Breadcrumb */}
          <div className="flex items-center gap-1 text-sm flex-wrap">
            <button
              onClick={() => { setCurrentPath(''); setPage(1); }}
              className="text-muted-foreground hover:text-primary transition-colors"
            >
              root
            </button>
            {breadcrumbParts.map((part, index) => (
              <>
                <span className="text-muted-foreground">/</span>
                <button
                  key={index}
                  onClick={() => handlePathClick(index)}
                  className="text-muted-foreground hover:text-primary transition-colors"
                >
                  {part}
                </button>
              </>
            ))}
          </div>

          {/* Toolbar */}
          <div className="flex items-center gap-2">
            {currentPath && (
              <Button variant="outline" size="sm" onClick={handleGoUp}>
                <ArrowUp className="w-3.5 h-3.5 mr-1" />
                Up
              </Button>
            )}
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none z-10" />
              <Input
                placeholder="Search files..."
                value={searchQuery}
                onChange={(e) => handleSearchChange(e.target.value)}
                className="pl-8 h-8 text-sm"
              />
            </div>
          </div>
        </div>

        {/* Column Headers */}
        <div className="grid grid-cols-[1fr_100px_120px_80px] gap-2 px-4 py-2 text-xs font-medium text-muted-foreground border-b border-border/30 bg-muted/20">
          <button 
            onClick={() => handleSort('name')}
            className="flex items-center gap-1 hover:text-primary text-left"
          >
            Name
            {sortBy === 'name' && (sortOrder === 'asc' ? <ArrowUpIcon className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
            {sortBy !== 'name' && <ArrowUpDown className="w-3 h-3 opacity-30" />}
          </button>
          <button 
            onClick={() => handleSort('size')}
            className="flex items-center gap-1 hover:text-primary text-right justify-end"
          >
            Size
            {sortBy === 'size' && (sortOrder === 'asc' ? <ArrowUpIcon className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
            {sortBy !== 'size' && <ArrowUpDown className="w-3 h-3 opacity-30" />}
          </button>
          <button 
            onClick={() => handleSort('modified')}
            className="flex items-center gap-1 hover:text-primary text-right justify-end"
          >
            Modified
            {sortBy === 'modified' && (sortOrder === 'asc' ? <ArrowUpIcon className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
            {sortBy !== 'modified' && <ArrowUpDown className="w-3 h-3 opacity-30" />}
          </button>
          <span className="text-right">Actions</span>
        </div>

        {/* File List */}
        <div 
          ref={listRef}
          onScroll={handleScroll}
          className="flex-1 overflow-auto"
        >
          {isLoading ? (
            <div className="flex items-center justify-center h-32">
              <Loader2 className="w-5 h-5 animate-spin text-primary" />
            </div>
          ) : error ? (
            <div className="flex items-center justify-center h-32">
              <span className="text-sm text-red-400">Failed to load files</span>
            </div>
          ) : data?.items.length === 0 ? (
            <div className="flex items-center justify-center h-32">
              <span className="text-sm text-muted-foreground">{searchQuery ? 'No matching files' : 'Empty directory'}</span>
            </div>
          ) : (
            <div className="divide-y divide-border/30">
              <AnimatePresence mode="popLayout">
                {visibleItems.map((item, index) => (
                  <motion.div
                    key={item.name}
                    layout
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="grid grid-cols-[1fr_100px_120px_80px] gap-2 px-4 py-2 items-center hover:bg-muted/30 group"
                    style={{ 
                      backgroundColor: index % 2 === 0 ? 'transparent' : 'rgba(128,128,128,0.03)' 
                    }}
                  >
                    {/* Name */}
                    <div className="flex items-center gap-2 min-w-0">
                      {item.type === 'directory' ? (
                        <button
                          onClick={() => handleNavigate(item.name)}
                          className="flex items-center gap-2 min-w-0 text-left hover:text-primary"
                        >
                          <Folder className="w-4 h-4 text-amber-400 shrink-0" />
                          <span className="text-sm truncate">{item.name}</span>
                        </button>
                      ) : (
                        <>
                          <File className="w-4 h-4 text-blue-400 shrink-0" />
                          <span className="text-sm truncate">{item.name}</span>
                        </>
                      )}
                    </div>

                    {/* Size */}
                    <span className="text-xs text-muted-foreground text-right">
                      {item.size !== null ? formatBytes(item.size) : <span className="italic">dir</span>}
                    </span>

                    {/* Modified */}
                    <span className="text-xs text-muted-foreground text-right">
                      {new Date(item.modified * 1000).toLocaleDateString()}
                    </span>

                    {/* Actions */}
                    <div className="flex items-center justify-end gap-1">
                      {item.type === 'file' && (
                        <Tooltip content="Download">
                          <button
                            onClick={() => handleDownload(item.name)}
                            className="p-1.5 rounded hover:bg-primary/10 text-muted-foreground hover:text-primary opacity-0 group-hover:opacity-100 transition-opacity"
                          >
                            <Download className="w-3.5 h-3.5" />
                          </button>
                        </Tooltip>
                      )}
                      <Tooltip content="Delete">
                        <button
                          onClick={() => handleDelete(item.name, item.type)}
                          disabled={deleting === item.name}
                          className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive disabled:opacity-50 opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          {deleting === item.name ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Trash2 className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </Tooltip>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
              
              {hasMore && (
                <div className="flex items-center justify-center py-4">
                  <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-border/50 flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {data?.total || 0} items
            {data?.total_pages && data.total_pages > 1 && ` (showing ${((data.page - 1) * PAGE_SIZE) + 1}-${Math.min(data.page * PAGE_SIZE, data.total)} of ${data.total})`}
          </span>
          
          {data?.total_pages && data.total_pages > 1 && (
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="h-7 w-7 p-0"
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <span className="text-xs px-2">
                {page} / {data.total_pages}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setPage(p => Math.min(data.total_pages, p + 1))}
                disabled={page >= data.total_pages}
                className="h-7 w-7 p-0"
              >
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          )}
        </div>
      </motion.div>
      {dialog}
    </div>
  );
}
