import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { feedsApi } from '../services/api';

interface ReprocessButtonProps {
  episodeGuid: string;
  isWhitelisted: boolean;
  feedId?: number;
  canModifyEpisodes?: boolean;
  className?: string;
  onReprocessStart?: () => void;
}

type ReprocessStep = 'transcript' | 'adDetection' | 'audioProcessing';

export default function ReprocessButton({
  episodeGuid,
  isWhitelisted,
  feedId,
  canModifyEpisodes = true,
  className = '',
  onReprocessStart
}: ReprocessButtonProps) {
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [selectedSteps, setSelectedSteps] = useState<ReprocessStep[]>(['transcript', 'adDetection', 'audioProcessing']);
  const queryClient = useQueryClient();

  const handleReprocessClick = async () => {
    if (!isWhitelisted) {
      setError('Post must be whitelisted before reprocessing');
      return;
    }

    setShowModal(true);
  };

  const handleStepToggle = (step: ReprocessStep) => {
    setSelectedSteps(prev => {
      if (prev.includes(step)) {
        // Don't allow unchecking if it's the only one checked
        if (prev.length === 1) return prev;
        return prev.filter(s => s !== step);
      }
      return [...prev, step];
    });
  };

  const handleConfirmReprocess = async () => {
    setShowModal(false);
    setIsReprocessing(true);
    setError(null);

    try {
      let response;

      if (selectedSteps.length === 3) {
        // All steps selected - use the full reprocess endpoint
        response = await feedsApi.reprocessPost(episodeGuid);
      } else if (selectedSteps.length === 1 && selectedSteps[0] === 'transcript') {
        // Only transcript selected - full reprocess (since transcript is first step)
        response = await feedsApi.reprocessPost(episodeGuid);
      } else if (selectedSteps.length === 1 && selectedSteps[0] === 'adDetection') {
        // Only ad detection selected
        response = await feedsApi.clearAdDetection(episodeGuid);
      } else if (selectedSteps.length === 1 && selectedSteps[0] === 'audioProcessing') {
        // Only audio processing selected
        response = await feedsApi.clearAudioProcessing(episodeGuid);
      } else if (selectedSteps.includes('adDetection') && selectedSteps.includes('audioProcessing') && !selectedSteps.includes('transcript')) {
        // Ad detection + audio processing (no transcript). Both calls'
        // responses must be checked -- a failed clearAdDetection that
        // resolves (rather than rejects) with status: 'error' must not be
        // silently dropped just because clearAudioProcessing succeeded.
        const adResult = await feedsApi.clearAdDetection(episodeGuid);
        const audioResult = await feedsApi.clearAudioProcessing(episodeGuid);
        const isOk = (r: { status: string }) => r.status === 'success' || r.status === 'started';

        if (!isOk(adResult) || !isOk(audioResult)) {
          const messages = [
            !isOk(adResult) ? adResult.message : null,
            !isOk(audioResult) ? audioResult.message : null,
          ].filter(Boolean).join('; ');
          response = { status: 'error', message: messages || 'Failed to clear ad detection/audio processing' };
        } else {
          response = audioResult;
        }
      } else {
        // Any other combination -- currently {transcript, adDetection} and
        // {transcript, audioProcessing} -- falls back to a full reprocess.
        // This is correct today because transcript is step 1, so selecting
        // it alongside a later step already implies redoing everything from
        // there; it's implicit rather than explicitly matched, so a future
        // 4th processing step would silently route here too -- revisit this
        // fallback if that happens.
        response = await feedsApi.reprocessPost(episodeGuid);
      }

      if (response.status === 'success' || response.status === 'started') {
        // Notify parent component that reprocessing started
        onReprocessStart?.();

        // Invalidate queries to refresh the UI
        if (feedId) {
          queryClient.invalidateQueries({ queryKey: ['episodes', feedId] });
        }
        queryClient.invalidateQueries({ queryKey: ['episode-stats', episodeGuid] });
      } else {
        setError(response.message || 'Failed to start reprocessing');
      }
    } catch (err: unknown) {
      console.error('Error starting reprocessing:', err);
      const errorMessage = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { message?: string } } }).response?.data?.message || 'Failed to start reprocessing'
        : 'Failed to start reprocessing';
      setError(errorMessage);
    } finally {
      setIsReprocessing(false);
    }
  };

  const getStepLabel = (step: ReprocessStep): string => {
    switch (step) {
      case 'transcript':
        return 'Transcription';
      case 'adDetection':
        return 'Ad Detection';
      case 'audioProcessing':
        return 'Audio Processing';
    }
  };

  const getStepDescription = (step: ReprocessStep): string => {
    switch (step) {
      case 'transcript':
        return 'Re-transcribe the audio from scratch';
      case 'adDetection':
        return 'Re-run ad detection on existing transcript (keeps transcript)';
      case 'audioProcessing':
        return 'Re-process audio cuts on existing ad detection (keeps transcript & ads)';
    }
  };

  if (!isWhitelisted || !canModifyEpisodes) {
    return null;
  }

  return (
    <div className={`${className}`}>
      <button
        onClick={handleReprocessClick}
        disabled={isReprocessing}
        className={`px-3 py-1 text-xs rounded font-medium transition-colors border ${
          isReprocessing
            ? 'bg-gray-500 text-white cursor-wait border-gray-500'
            : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50 hover:border-gray-400 hover:text-gray-900'
        }`}
        title={
          isReprocessing
            ? 'Clearing data and reprocessing...'
            : 'Choose which processing steps to reprocess'
        }
      >
        {isReprocessing ? (
          '⏳ Reprocessing...'
        ) : (
          'Reprocess'
        )}
      </button>

      {error && (
        <div className="text-xs text-red-600 mt-1">
          {error}
        </div>
      )}

      {/* Step Selection Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-md w-full overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b">
              <h2 className="text-xl font-bold text-gray-900">Select Steps to Reprocess</h2>
              <button
                onClick={() => setShowModal(false)}
                className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Content */}
            <div className="p-6">
              <p className="text-gray-600 mb-4 text-sm">
                Choose which processing steps to reprocess. Earlier steps will also be cleared when reprocessing later steps.
              </p>

              {/* Step Checkboxes */}
              <div className="space-y-4 mb-6">
                {(['transcript', 'adDetection', 'audioProcessing'] as ReprocessStep[]).map((step) => (
                  <label
                    key={step}
                    className={`flex items-start p-3 border rounded-lg cursor-pointer transition-colors ${
                      selectedSteps.includes(step)
                        ? 'border-orange-500 bg-orange-50'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedSteps.includes(step)}
                      onChange={() => handleStepToggle(step)}
                      className="mt-1 h-4 w-4 text-orange-600 focus:ring-orange-500 border-gray-300 rounded"
                    />
                    <div className="ml-3">
                      <div className="font-medium text-gray-900">{getStepLabel(step)}</div>
                      <div className="text-sm text-gray-500">{getStepDescription(step)}</div>
                    </div>
                  </label>
                ))}
              </div>

              {/* Warning */}
              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-6">
                <div className="flex">
                  <svg className="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  <div className="ml-2 text-sm text-yellow-700">
                    {selectedSteps.length === 3 ? (
                      'This will delete ALL processing data and start from scratch.'
                    ) : selectedSteps.includes('transcript') ? (
                      'This will delete transcript, ad detection, and audio processing data.'
                    ) : selectedSteps.includes('adDetection') ? (
                      'This will delete ad detection and audio processing data, but keep the transcript.'
                    ) : (
                      'This will delete only the processed audio file, keeping transcript and ad detection.'
                    )}
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 hover:border-gray-400 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleConfirmReprocess}
                  disabled={selectedSteps.length === 0}
                  className="px-4 py-2 text-sm font-medium text-white bg-orange-600 rounded-md hover:bg-orange-700 transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed"
                >
                  Reprocess {selectedSteps.length > 0 && `(${selectedSteps.length} step${selectedSteps.length > 1 ? 's' : ''})`}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
