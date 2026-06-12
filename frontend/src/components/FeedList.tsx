import { useMemo, useState } from 'react';
import { toast } from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { feedsApi } from '../services/api';
import type { Feed } from '../types';

interface FeedListProps {
  feeds: Feed[];
  onFeedDeleted: () => void;
  onFeedSelected: (feed: Feed) => void;
  selectedFeedId?: number;
  onFeedsUpdated?: () => void;
}

export default function FeedList({ feeds, onFeedSelected, selectedFeedId, onFeedsUpdated }: FeedListProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [isBulkUpdating, setIsBulkUpdating] = useState(false);
  const [bulkRetentionInput, setBulkRetentionInput] = useState('');
  const { requireAuth, user } = useAuth();
  const showMembership = Boolean(requireAuth && user?.role === 'admin');
  // Admin in no-auth mode too (matches FeedDetail), so bulk select works without auth.
  const isAdmin = !requireAuth || user?.role === 'admin';

  const feedsArray = Array.isArray(feeds) ? feeds : [];

  const filteredFeeds = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    if (!term) return feedsArray;
    return feedsArray.filter((feed) => {
      const title = feed.title?.toLowerCase() ?? '';
      const author = feed.author?.toLowerCase() ?? '';
      return title.includes(term) || author.includes(term);
    });
  }, [feedsArray, searchTerm]);

  const toggleSelection = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSelectAll = () => {
    if (selectedIds.size === filteredFeeds.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredFeeds.map((f) => f.id)));
    }
  };

  const exitSelectionMode = () => {
    setSelectionMode(false);
    setSelectedIds(new Set());
    setBulkRetentionInput('');
  };

  const handleBulkAction = async (override: boolean | null) => {
    if (selectedIds.size === 0) return;
    setIsBulkUpdating(true);
    try {
      const result = await feedsApi.bulkUpdateFeedSettings(
        Array.from(selectedIds),
        { auto_whitelist_new_episodes_override: override }
      );
      const label = override === true ? 'enabled' : override === false ? 'disabled' : 'reset to global';
      toast.success(`Auto-whitelist ${label} for ${result.updated} feed${result.updated !== 1 ? 's' : ''}`);
      onFeedsUpdated?.();
      exitSelectionMode();
    } catch {
      toast.error('Failed to update feeds');
    } finally {
      setIsBulkUpdating(false);
    }
  };

  const handleBulkRetention = async () => {
    if (selectedIds.size === 0) return;
    const trimmed = bulkRetentionInput.trim();
    let retention: number | null;
    if (trimmed === '') {
      retention = null; // clear per-feed limit
    } else {
      const n = parseInt(trimmed, 10);
      if (isNaN(n) || n < 1) {
        toast.error('Retention must be a whole number of 1 or more (or blank to clear).');
        return;
      }
      retention = n;
    }
    setIsBulkUpdating(true);
    try {
      const result = await feedsApi.bulkUpdateFeedSettings(
        Array.from(selectedIds),
        { episode_retention_count: retention }
      );
      const label = retention === null ? 'cleared' : `set to ${retention}`;
      toast.success(`Retention ${label} for ${result.updated} feed${result.updated !== 1 ? 's' : ''}`);
      onFeedsUpdated?.();
      exitSelectionMode();
    } catch {
      toast.error('Failed to update feeds');
    } finally {
      setIsBulkUpdating(false);
    }
  };

  if (feedsArray.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500 text-lg">No podcast feeds added yet.</p>
        <p className="text-gray-400 mt-2">Click "Add Feed" to get started.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="mb-3 flex gap-2">
        <label htmlFor="feed-search" className="sr-only">Search feeds</label>
        <input
          id="feed-search"
          type="search"
          placeholder="Search feeds"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          className="flex-1 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-500 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
        {isAdmin && (
          <button
            onClick={() => {
              if (selectionMode) exitSelectionMode();
              else setSelectionMode(true);
            }}
            className={`px-3 py-2 rounded-lg border text-sm font-medium transition-colors ${
              selectionMode
                ? 'bg-blue-600 text-white border-blue-600'
                : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
            }`}
          >
            {selectionMode ? 'Cancel' : 'Select'}
          </button>
        )}
      </div>

      {selectionMode && (
        <div className="mb-2 flex items-center gap-2 text-sm">
          <button
            onClick={handleSelectAll}
            className="text-blue-600 hover:underline"
          >
            {selectedIds.size === filteredFeeds.length ? 'Deselect all' : 'Select all'}
          </button>
          <span className="text-gray-400">|</span>
          <span className="text-gray-600">{selectedIds.size} selected</span>
        </div>
      )}

      <div className="space-y-2 overflow-y-auto h-full pb-20">
        {filteredFeeds.length === 0 ? (
          <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-center">
            <p className="text-sm text-gray-500">
              No podcasts match &quot;{searchTerm}&quot;
            </p>
          </div>
        ) : (
          filteredFeeds.map((feed) => (
            <div
              key={feed.id}
              className={`bg-white rounded-lg shadow border transition-all ${
                selectionMode
                  ? selectedIds.has(feed.id)
                    ? 'ring-2 ring-blue-500 border-blue-200 cursor-pointer'
                    : 'cursor-pointer hover:border-blue-300'
                  : `cursor-pointer hover:shadow-md group ${
                      selectedFeedId === feed.id ? 'ring-2 ring-blue-500 border-blue-200' : ''
                    }`
              }`}
              onClick={() => {
                if (selectionMode) toggleSelection(feed.id);
                else onFeedSelected(feed);
              }}
            >
              <div className="p-4">
                <div className="flex items-start gap-3">
                  {selectionMode && (
                    <div className="flex-shrink-0 flex items-center pt-0.5">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(feed.id)}
                        onChange={() => toggleSelection(feed.id)}
                        onClick={(e) => e.stopPropagation()}
                        className="w-4 h-4 text-blue-600 rounded border-gray-300"
                      />
                    </div>
                  )}

                  {/* Podcast Image */}
                  {!selectionMode && (
                    <div className="flex-shrink-0">
                      {feed.image_url ? (
                        <img
                          src={feed.image_url}
                          alt={feed.title}
                          className="w-12 h-12 rounded-lg object-cover"
                        />
                      ) : (
                        <div className="w-12 h-12 rounded-lg bg-gray-200 flex items-center justify-center">
                          <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                          </svg>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Feed Info */}
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-gray-900 line-clamp-2">{feed.title}</h3>
                    {feed.author && (
                      <p className="text-sm text-gray-600 mt-1">by {feed.author}</p>
                    )}
                    <div className="flex items-center justify-between mt-2">
                      <span className="text-xs text-gray-500">{feed.posts_count} episodes</span>
                      {showMembership && (
                        <div className="flex items-center gap-2">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                              feed.is_member
                                ? 'bg-green-100 text-green-700 border border-green-200'
                                : 'bg-gray-100 text-gray-600 border border-gray-200'
                            }`}
                          >
                            {feed.is_member ? 'Joined' : 'Not joined'}
                          </span>
                          {feed.is_member && feed.is_active_subscription === false && (
                            <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-100 text-amber-700 border border-amber-200">
                              Paused
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Bulk action bar */}
      {selectionMode && selectedIds.size > 0 && (
        <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 shadow-lg p-3 flex flex-col gap-2 z-50 md:static md:mt-2 md:rounded-lg md:border md:shadow-none">
          <span className="text-sm text-gray-600 font-medium">
            {selectedIds.size} feed{selectedIds.size !== 1 ? 's' : ''} selected
          </span>

          {/* Auto-whitelist row */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-gray-500 w-24 shrink-0">Auto-whitelist</span>
            <button
              disabled={isBulkUpdating}
              onClick={() => handleBulkAction(true)}
              className="px-3 py-1.5 text-xs font-medium bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50"
            >
              Enable
            </button>
            <button
              disabled={isBulkUpdating}
              onClick={() => handleBulkAction(false)}
              className="px-3 py-1.5 text-xs font-medium bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50"
            >
              Disable
            </button>
            <button
              disabled={isBulkUpdating}
              onClick={() => handleBulkAction(null)}
              className="px-3 py-1.5 text-xs font-medium bg-gray-500 text-white rounded-md hover:bg-gray-600 disabled:opacity-50"
            >
              Use global
            </button>
          </div>

          {/* Retention row */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-gray-500 w-24 shrink-0">Retention limit</span>
            <input
              type="number"
              min={1}
              placeholder="blank = clear"
              value={bulkRetentionInput}
              onChange={(e) => setBulkRetentionInput(e.target.value)}
              disabled={isBulkUpdating}
              className="w-28 text-xs border border-gray-300 rounded-md px-2 py-1.5 bg-white disabled:opacity-50"
            />
            <button
              disabled={isBulkUpdating}
              onClick={handleBulkRetention}
              className="px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
            >
              Apply to selected
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
