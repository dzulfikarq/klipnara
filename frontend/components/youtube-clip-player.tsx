"use client";

import { useEffect, useRef } from "react";
import { youtubePlayerErrorMessage } from "@/lib/youtube-clip.mjs";

type PlayerStateEvent = { data: number; target: YouTubePlayerApi };
type PlayerErrorEvent = { data: number };

export type YouTubePlayerApi = {
  getCurrentTime: () => number;
  getDuration: () => number;
  seekTo: (seconds: number, allowSeekAhead: boolean) => void;
  playVideo: () => void;
  pauseVideo: () => void;
  destroy: () => void;
};

type YouTubeApi = {
  Player: new (target: HTMLElement, options: {
    videoId: string;
    playerVars: Record<string, number | string>;
    events: {
      onReady: (event: PlayerStateEvent) => void;
      onStateChange: (event: PlayerStateEvent) => void;
      onError: (event: PlayerErrorEvent) => void;
    };
  }) => YouTubePlayerApi;
};

declare global {
  interface Window {
    YT?: YouTubeApi;
    onYouTubeIframeAPIReady?: () => void;
  }
}

let apiPromise: Promise<void> | null = null;

function loadIframeApi() {
  if (window.YT?.Player) return Promise.resolve();
  if (apiPromise) return apiPromise;
  apiPromise = new Promise<void>((resolve, reject) => {
    const scriptId = "youtube-iframe-api";
    const script = document.getElementById(scriptId) as HTMLScriptElement | null;
    const previousReady = window.onYouTubeIframeAPIReady;
    let timeout: number;
    const fail = () => {
      window.clearTimeout(timeout);
      window.onYouTubeIframeAPIReady = previousReady;
      document.getElementById(scriptId)?.remove();
      reject(new Error("IFrame Player API gagal dimuat. Periksa jaringan atau pemblokir konten."));
    };
    window.onYouTubeIframeAPIReady = () => {
      window.clearTimeout(timeout);
      window.onYouTubeIframeAPIReady = previousReady;
      previousReady?.();
      if (window.YT?.Player) resolve();
      else reject(new Error("YouTube IFrame Player API tidak siap."));
    };
    timeout = window.setTimeout(fail, 15000);
    if (script) script.addEventListener("error", fail, { once: true });
    else {
      const next = document.createElement("script");
      next.id = scriptId;
      next.src = "https://www.youtube.com/iframe_api";
      next.async = true;
      next.onerror = fail;
      document.head.appendChild(next);
    }
  }).catch((reason) => {
    apiPromise = null;
    throw reason;
  });
  return apiPromise;
}

type Props = {
  videoId: string;
  startAt: number;
  endAt: number;
  reloadKey: number;
  onPlayer: (player: YouTubePlayerApi | null) => void;
  onTime: (seconds: number) => void;
  onDuration: (seconds: number) => void;
  onPlaying: (playing: boolean) => void;
  onError: (message: string) => void;
};

export function YouTubeClipPlayer({ videoId, startAt, endAt, reloadKey, onPlayer, onTime, onDuration, onPlaying, onError }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onPlayer, onTime, onDuration, onPlaying, onError });
  const range = useRef({ startAt, endAt });
  useEffect(() => { callbacks.current = { onPlayer, onTime, onDuration, onPlaying, onError }; }, [onPlayer, onTime, onDuration, onPlaying, onError]);
  useEffect(() => { range.current = { startAt, endAt }; }, [startAt, endAt]);

  useEffect(() => {
    let disposed = false;
    let player: YouTubePlayerApi | null = null;
    let poll: number | null = null;
    let readyTimeout: number | null = null;
    let playerReady = false;
    const stopPolling = () => {
      if (poll !== null) window.clearInterval(poll);
      poll = null;
      callbacks.current.onPlaying(false);
    };
    const publishTime = (target: YouTubePlayerApi) => {
      const current = target.getCurrentTime();
      const duration = target.getDuration();
      if (Number.isFinite(current)) callbacks.current.onTime(current);
      if (Number.isFinite(duration) && duration > 0) callbacks.current.onDuration(duration);
      const selected = range.current;
      if (selected.endAt > selected.startAt && current >= selected.endAt) {
        target.pauseVideo();
        target.seekTo(selected.endAt, false);
        stopPolling();
      }
    };

    loadIframeApi().then(() => {
      if (disposed || !host.current || !window.YT?.Player) return;
      player = new window.YT.Player(host.current, {
        videoId,
        playerVars: { controls: 1, enablejsapi: 1, origin: window.location.origin, playsinline: 1, rel: 0, start: Math.floor(Math.max(0, startAt)) },
        events: {
          onReady: (event) => {
            if (disposed) return;
            playerReady = true;
            if (readyTimeout !== null) window.clearTimeout(readyTimeout);
            player = event.target;
            callbacks.current.onPlayer(player);
            publishTime(player);
          },
          onStateChange: (event) => {
            if (event.data === 1) {
              callbacks.current.onPlaying(true);
              if (poll === null) poll = window.setInterval(() => publishTime(event.target), 200);
              publishTime(event.target);
            } else {
              stopPolling();
              publishTime(event.target);
            }
          },
          onError: (event) => {
            if (readyTimeout !== null) window.clearTimeout(readyTimeout);
            callbacks.current.onError(youtubePlayerErrorMessage(event.data));
          },
        },
      });
      if (!playerReady) {
        readyTimeout = window.setTimeout(() => {
          if (!disposed) callbacks.current.onError("YouTube player tidak merespons. Embed mungkin diblokir atau jaringan tidak tersedia.");
        }, 12000);
      }
    }).catch((reason: unknown) => {
      if (!disposed) callbacks.current.onError((reason as Error).message);
    });

    return () => {
      disposed = true;
      stopPolling();
      if (readyTimeout !== null) window.clearTimeout(readyTimeout);
      callbacks.current.onPlayer(null);
      player?.destroy();
    };
  }, [videoId, reloadKey]);

  return <div ref={host} className="youtube-iframe-host" aria-label="YouTube video preview"/>;
}
