import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FilmIcon, LoaderCircleIcon, PlayIcon, XIcon } from 'lucide-react';
import type { MediaPlayerInstance } from '@/components/media-player';
import { VideoPlayer } from '@/components/video-player';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { apiJson, apiPath } from '@/lib/api/client';

interface DemoManifest {
  source: {
    code: string;
    label: string;
    video: string;
    script: string;
  };
  dubbed: Array<{
    code: string;
    label: string;
    video: string;
    script: string;
    dir?: 'ltr' | 'rtl';
  }>;
}

const DEMO_BASE = '/demo_audio/demo/dubbing';
const PLAYBACK_GROUP = 'dubbing-demo-comparison';

export function DubbingDemo({ onDismiss, onTry }: { onDismiss: () => void; onTry: () => void }) {
  const { t } = useTranslation();
  const [manifest, setManifest] = useState<DemoManifest | null>(null);
  const [failed, setFailed] = useState(false);
  const [language, setLanguage] = useState('es');
  const [synchronized, setSynchronized] = useState(true);
  const sourcePlayer = useRef<MediaPlayerInstance>(null);
  const dubbedPlayer = useRef<MediaPlayerInstance>(null);
  const mirroring = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    void apiJson<DemoManifest>(`${DEMO_BASE}/manifest.json`, { signal: controller.signal })
      .then(setManifest)
      .catch(() => !controller.signal.aborted && setFailed(true));
    return () => controller.abort();
  }, []);

  if (failed) return null;
  if (!manifest)
    return (
      <div className="flex h-24 items-center justify-center rounded-xl border border-border/50 bg-muted/20 text-xs text-muted-foreground">
        <LoaderCircleIcon className="mr-2 size-4 animate-spin motion-reduce:animate-none" />
        {t('demo.dubbing_loading')}
      </div>
    );

  const dubbed = manifest.dubbed.find((item) => item.code === language) || manifest.dubbed[0];
  if (!dubbed) return null;

  const mirror = (
    from: MediaPlayerInstance | null,
    to: MediaPlayerInstance | null,
    action: 'play' | 'pause' | 'seek',
  ) => {
    if (!synchronized || mirroring.current || !from || !to) return;
    mirroring.current = true;
    try {
      to.currentTime = from.currentTime;
      if (action === 'play' && to.paused) void to.play().catch(() => {});
      if (action === 'pause' && !to.paused) void to.pause();
    } finally {
      queueMicrotask(() => {
        mirroring.current = false;
      });
    }
  };

  const card = (
    label: string,
    tag: string,
    video: string,
    script: string,
    player: React.RefObject<MediaPlayerInstance | null>,
    peer: React.RefObject<MediaPlayerInstance | null>,
    direction?: 'ltr' | 'rtl',
  ) => (
    <article className="min-w-0 space-y-2">
      <div className="flex items-center gap-2 text-xs font-medium">
        <span>{label}</span>
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{tag}</span>
      </div>
      <VideoPlayer
        playerRef={player}
        playbackGroup={PLAYBACK_GROUP}
        load="eager"
        src={{ src: apiPath(`${DEMO_BASE}/${video}`), type: 'video/mp4' }}
        source={`${PLAYBACK_GROUP}-${tag}`}
        onPlay={() => mirror(player.current, peer.current, 'play')}
        onPause={() => mirror(player.current, peer.current, 'pause')}
        onSeeked={() => mirror(player.current, peer.current, 'seek')}
      />
      <p
        dir={direction}
        className="line-clamp-3 rounded-lg bg-background/35 p-2 text-left text-xs leading-5 text-muted-foreground"
      >
        {script}
      </p>
    </article>
  );

  return (
    <section className="glass-panel w-full space-y-4 rounded-2xl border border-border/60 bg-card/35 p-4 text-left shadow-sm">
      <header className="flex flex-wrap items-center gap-3">
        <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <FilmIcon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium">{t('demo.dubbing_title')}</h3>
          <p className="text-xs text-muted-foreground">{t('demo.dubbing_picker')}</p>
        </div>
        <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
          {t('demo.dubbing_sync')}
          <Switch checked={synchronized} onCheckedChange={setSynchronized} />
        </label>
        <Button
          size="icon-xs"
          variant="ghost"
          aria-label={t('demo.dubbing_dismiss')}
          onClick={onDismiss}
        >
          <XIcon />
        </Button>
      </header>
      <div className="grid gap-4 min-[1100px]:grid-cols-2">
        {card(
          manifest.source.label,
          t('demo.original_tag'),
          manifest.source.video,
          manifest.source.script,
          sourcePlayer,
          dubbedPlayer,
        )}
        {card(
          dubbed.label,
          t('demo.dubbed_tag'),
          dubbed.video,
          dubbed.script,
          dubbedPlayer,
          sourcePlayer,
          dubbed.dir,
        )}
      </div>
      <footer className="flex flex-wrap items-center gap-1.5">
        {manifest.dubbed.map((item) => (
          <Button
            key={item.code}
            size="xs"
            variant={item.code === dubbed.code ? 'secondary' : 'ghost'}
            aria-pressed={item.code === dubbed.code}
            onClick={() => setLanguage(item.code)}
          >
            {item.label}
          </Button>
        ))}
        <Button size="sm" className="ml-auto" onClick={onTry}>
          <PlayIcon />
          {t('demo.dubbing_cta')}
        </Button>
      </footer>
    </section>
  );
}
