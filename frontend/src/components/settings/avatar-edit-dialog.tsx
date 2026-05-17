import { useState, useRef, useCallback } from 'react';
import Cropper from 'react-easy-crop';
import { Upload, Trash2, Globe, ZoomIn, ZoomOut, Check } from 'lucide-react';
import { Slider } from '../ui/slider';
import { useToast } from '../../stores/toast-store';
import { api } from '../../lib/api';
import type { User } from '../../types/api';
import { Button } from '../ui/button';
import { Modal } from '../ui/modal';
import { cn } from '../../lib/utils';

interface Point {
  x: number;
  y: number;
}

interface Area {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface AvatarEditDialogProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  currentAvatarUrl?: string;
  fallbackInitial: string;
  useGravatar: boolean;
  onSaved: (updated: Partial<import('../../types/api').User>) => void;
  onToggleGravatar: () => Promise<void>;
}

const MAX_FILE_SIZE = 2 * 1024 * 1024;
const OUTPUT_SIZE = 512;

type Mode = 'source' | 'crop';

function createImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = 'anonymous';
    image.addEventListener('load', () => resolve(image));
    image.addEventListener('error', (err) => reject(err));
    image.src = url;
  });
}

async function getCroppedImg(imageSrc: string, pixelCrop: Area): Promise<Blob> {
  const image = await createImage(imageSrc);
  const canvas = document.createElement('canvas');
  canvas.width = OUTPUT_SIZE;
  canvas.height = OUTPUT_SIZE;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('No canvas context');

  ctx.drawImage(
    image,
    pixelCrop.x,
    pixelCrop.y,
    pixelCrop.width,
    pixelCrop.height,
    0,
    0,
    OUTPUT_SIZE,
    OUTPUT_SIZE
  );

  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('Canvas export failed'));
    }, 'image/jpeg', 0.92);
  });
}

/* ------------------------------------------------------------------ */
/*  Source selection mode                                              */
/* ------------------------------------------------------------------ */

function SourceButton({
  active,
  icon: Icon,
  label,
  onClick,
  disabled,
  variant = 'default',
}: {
  active?: boolean;
  icon: React.ElementType;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  variant?: 'default' | 'danger';
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'flex flex-col items-center justify-center gap-1.5 px-3 py-3 rounded-xl border text-sm font-medium transition-all',
        'disabled:opacity-40 disabled:cursor-not-allowed',
        active
          ? 'border-primary bg-primary/10 text-primary'
          : variant === 'danger'
            ? 'border-border/60 bg-background hover:border-red-500/40 hover:bg-red-500/5 hover:text-red-500 text-muted-foreground'
            : 'border-border/60 bg-background hover:border-primary/40 hover:bg-primary/5 hover:text-primary text-muted-foreground'
      )}
    >
      <Icon className="w-5 h-5" />
      <span>{label}</span>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Dialog                                                             */
/* ------------------------------------------------------------------ */

export function AvatarEditDialog({
  open,
  onOpenChange,
  currentAvatarUrl,
  fallbackInitial,
  useGravatar,
  onSaved,
  onToggleGravatar,
}: AvatarEditDialogProps) {
  const { success, error } = useToast();

  const [mode, setMode] = useState<Mode>('source');
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [crop, setCrop] = useState<Point>({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [croppedAreaPixels, setCroppedAreaPixels] = useState<Area | null>(null);
  const [uploading, setUploading] = useState(false);
  const [togglingGravatar, setTogglingGravatar] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  /* State is reset via key prop on mount */

  const activeSource = useGravatar
    ? 'gravatar'
    : currentAvatarUrl
      ? 'custom'
      : 'default';

  const previewUrl = activeSource === 'default' ? undefined : currentAvatarUrl;

  /* File selection → crop mode */
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_FILE_SIZE) {
      error('File too large', 'Maximum file size is 2MB');
      return;
    }
    const reader = new FileReader();
    reader.onloadend = () => {
      setImageSrc(reader.result as string);
      setMode('crop');
      setCrop({ x: 0, y: 0 });
      setZoom(1);
      setCroppedAreaPixels(null);
    };
    reader.readAsDataURL(file);
  };

  /* Cropper callbacks */
  const onCropChange = useCallback((c: Point) => setCrop(c), []);
  const onZoomChange = useCallback((z: number) => setZoom(z), []);
  const onCropComplete = useCallback((_: Area, croppedPixels: Area) => {
    setCroppedAreaPixels(croppedPixels);
  }, []);

  /* Upload cropped image */
  const handleUpload = async () => {
    if (!imageSrc || !croppedAreaPixels) return;
    setUploading(true);
    try {
      const blob = await getCroppedImg(imageSrc, croppedAreaPixels);
      const file = new File([blob], 'avatar.jpg', { type: 'image/jpeg' });
      const formData = new FormData();
      formData.append('file', file);
      const token = localStorage.getItem('nukelab-token');
      const res = await fetch(`${import.meta.env.VITE_API_URL || '/api'}/users/me/avatar`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (!res.ok) throw new Error('Upload failed');
      await res.json();
      const fresh = await api.get<User>('/users/me/profile');
      onSaved(fresh);
      success('Avatar updated', 'Your profile picture has been saved');
      onOpenChange(false);
    } catch {
      error('Upload failed', 'Failed to save avatar');
    } finally {
      setUploading(false);
    }
  };

  /* Remove custom avatar */
  const handleRemove = async () => {
    try {
      const updated = await api.put<Partial<User>>('/users/me/profile', {
        avatar_url: '',
      });
      onSaved(updated);
      success('Avatar removed', 'Your profile picture has been reset');
      onOpenChange(false);
    } catch {
      error('Failed to remove', 'Please try again');
    }
  };

  /* Toggle Gravatar from inside the dialog */
  const handleToggleGravatar = async () => {
    if (useGravatar) return;
    setTogglingGravatar(true);
    try {
      await onToggleGravatar();
      success('Gravatar enabled', 'Your Gravatar is now active');
    } catch {
      error('Update failed', 'Failed to enable Gravatar');
    } finally {
      setTogglingGravatar(false);
    }
  };

  const title = mode === 'crop' ? 'Crop & Adjust' : 'Profile Picture';

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={title} className="max-w-md">
      <div className="flex flex-col items-center gap-5 px-5 pb-6">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          className="hidden"
          onChange={handleFileSelect}
        />

        {/* ========== SOURCE MODE ========== */}
        {mode === 'source' && (
          <>
            {/* Main preview */}
            <div className="relative">
              <div className="w-[200px] h-[200px] rounded-2xl overflow-hidden bg-muted ring-1 ring-border/40">
                {previewUrl ? (
                  <img src={previewUrl} alt="Current avatar" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-primary/30 to-primary/10">
                    <span className="text-7xl font-bold text-primary">{fallbackInitial}</span>
                  </div>
                )}
              </div>

              {/* Active source badge */}
              <div className="absolute -bottom-2.5 left-1/2 -translate-x-1/2">
                <span className="px-3 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider bg-background border border-border/60 text-muted-foreground shadow-sm whitespace-nowrap">
                  {activeSource === 'gravatar' && 'Gravatar'}
                  {activeSource === 'custom' && 'Custom'}
                  {activeSource === 'default' && 'Default'}
                </span>
              </div>
            </div>

            {/* Source buttons */}
            <div className="grid grid-cols-3 gap-2 w-full">
              <SourceButton
                icon={Upload}
                label="Upload New"
                onClick={() => fileInputRef.current?.click()}
              />
              <SourceButton
                active={useGravatar}
                icon={Globe}
                label={togglingGravatar ? '…' : 'Gravatar'}
                onClick={handleToggleGravatar}
                disabled={togglingGravatar}
              />
              <SourceButton
                icon={Trash2}
                label="Remove"
                variant="danger"
                onClick={handleRemove}
                disabled={activeSource === 'default' || activeSource === 'gravatar'}
              />
            </div>

            {activeSource === 'gravatar' && (
              <p className="text-xs text-muted-foreground text-center">
                Disable Gravatar in Preferences to remove or upload a custom picture.
              </p>
            )}
          </>
        )}

        {/* ========== CROP MODE ========== */}
        {mode === 'crop' && imageSrc && (
          <>
            {/* Cropper */}
            <div
              className="relative w-full rounded-2xl overflow-hidden bg-muted"
              style={{ height: 320 }}
            >
              <Cropper
                image={imageSrc}
                crop={crop}
                zoom={zoom}
                aspect={1}
                cropShape="rect"
                showGrid={true}
                onCropChange={onCropChange}
                onZoomChange={onZoomChange}
                onCropComplete={onCropComplete}
                minZoom={0.5}
                maxZoom={4}
                zoomSpeed={0.4}
                style={{
                  containerStyle: { borderRadius: '1rem' },
                  cropAreaStyle: {
                    border: '2px solid rgba(255,255,255,0.9)',
                    boxShadow: '0 0 0 9999px rgba(0,0,0,0.55)',
                  },
                }}
              />
            </div>

            {/* Zoom slider */}
            <div className="flex items-center gap-3 w-full">
              <ZoomOut className="w-4 h-4 text-muted-foreground shrink-0" />
              <Slider
                min={0.5}
                max={4}
                step={0.05}
                value={zoom}
                onChange={setZoom}
              />
              <ZoomIn className="w-4 h-4 text-muted-foreground shrink-0" />
            </div>

            <p className="text-xs text-muted-foreground text-center">
              Drag to pan · Scroll or pinch to zoom
            </p>

            {/* Crop actions */}
            <div className="flex items-center gap-2 w-full">
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                onClick={() => {
                  setMode('source');
                  setImageSrc(null);
                  setCrop({ x: 0, y: 0 });
                  setZoom(1);
                  setCroppedAreaPixels(null);
                }}
              >
                Cancel
              </Button>
              <Button
                type="button"
                className="flex-1"
                loading={uploading}
                onClick={handleUpload}
              >
                <Check className="w-4 h-4 mr-2" />
                Save Avatar
              </Button>
            </div>
          </>
        )}

        {/* Footer hint */}
        {mode === 'source' && (
          <p className="text-xs text-muted-foreground text-center">
            JPEG, PNG, WebP, GIF · Max 2MB
          </p>
        )}
      </div>
    </Modal>
  );
}
