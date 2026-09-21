/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 * Client for the document-translation API (`/api/document-translations`).
 *
 * The API speaks camelCase (pydantic `alias_generator=to_camel`); query
 * parameters are FastAPI arguments and stay snake_case.
 */

import {HttpClient, HttpHeaders, HttpParams} from '@angular/common/http';
import {Injectable, inject} from '@angular/core';
import {Observable} from 'rxjs';
import {switchMap} from 'rxjs/operators';
import {environment} from '../../environments/environment';

/** A section as the backend summarises it for the review outline. */
export interface ApiOutlineSection {
  id: string;
  title: string;
  segments: number;
  translatable: number;
  tables: number;
}

export interface ApiOutlineChapter extends ApiOutlineSection {
  sections: ApiOutlineSection[];
}

/**
 * `stats` mixes three sources: per-kind segment counts from the parser, Word
 * document properties, and the review outline.
 */
export interface ApiJobStats {
  total?: number;
  translatable?: number;
  heading?: number;
  prose?: number;
  table_label?: number;
  numeric?: number;
  skip?: number;
  pages?: number;
  words?: number;
  trackedChanges?: number;
  tracked_changes?: number;
  chapters?: ApiOutlineChapter[];
}

export interface ApiJobProgress {
  translated: number;
  failed: number;
  total: number;
  /** section id → 'done' | 'fail' (absent means not started yet) */
  sections: Record<string, string>;
}

export interface ApiFinding {
  segmentIndex: number;
  type: string;
  severity: 'error' | 'warning';
  msg: string;
  term?: string | null;
  expected?: string | null;
  found?: string | null;
}

/** `uploaded` → `translating` → `review` → `completed`, or `failed`. */
export type ApiJobStatus =
  | 'uploaded'
  | 'translating'
  | 'review'
  | 'completed'
  | 'failed';

export interface ApiJob {
  id: string;
  filename: string;
  status: ApiJobStatus;
  targetMarket?: string | null;
  modelId?: string | null;
  /** Figures and dates are renotated for the market when exported. */
  localiseNumbers?: boolean;
  sourceGcsUri?: string | null;
  outputGcsUri?: string | null;
  stats?: ApiJobStats | null;
  progress?: ApiJobProgress | null;
  qaFindings?: ApiFinding[] | null;
  errorMessage?: string | null;
  createdBy?: string | null;
  createdAt?: string;
  updatedAt?: string;
  /**
   * Computed server-side: the run says `translating` but its worker is gone
   * (the task lives in one Cloud Run instance and the service scales to zero).
   * The progress it did make is intact, so this offers Resume rather than a
   * spinner that never moves.
   */
  stalled?: boolean;
}

export type ApiSegmentKind =
  | 'heading'
  | 'prose'
  | 'table_label'
  | 'numeric'
  | 'skip';

/** `locked` is a non-translatable segment (a figure cell); it never changes. */
export type ApiSegmentStatus =
  | 'pending'
  | 'locked'
  | 'translated'
  | 'approved'
  | 'failed';

export interface ApiSegment {
  id: number;
  jobId: string;
  /** Position in document order — the id used in the segment routes. */
  segIndex: number;
  kind: ApiSegmentKind;
  sectionId?: string | null;
  sectionPath?: string[] | null;
  tableIndex?: number | null;
  rowIndex?: number | null;
  headingLevel?: number | null;
  bold: boolean;
  sourceText: string;
  translation?: string | null;
  status: ApiSegmentStatus;
  provenance?: 'tm' | 'ai' | 'edited' | null;
  finding?: ApiFinding | null;
}

/** What a replay of the quality checks left standing. */
export interface ApiRecheck {
  findings: number;
  blocking: number;
  localiseNumbers: boolean;
}

/** Where the browser may PUT the .docx, bypassing the backend entirely. */
export interface ApiUploadUrl {
  uploadUrl: string;
  gcsUri: string;
}

export interface ApiReuseEstimate {
  total: number;
  reusable: number;
  pct: number;
}

const DOCX_MIME =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

/**
 * Below this a file rides the request body, which keeps the path every small
 * document already uses. Cloud Run's own ceiling is 32 MiB; the margin covers
 * multipart overhead.
 */
const DIRECT_POST_LIMIT_BYTES = 24 * 1024 * 1024;

@Injectable({providedIn: 'root'})
export class DocumentTranslationsService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.backendURL}/document-translations`;

  listJobs(): Observable<ApiJob[]> {
    return this.http.get<ApiJob[]>(this.base);
  }

  getJob(jobId: string): Observable<ApiJob> {
    return this.http.get<ApiJob>(`${this.base}/${jobId}`);
  }

  /**
   * Uploads the .docx and parses it; the job comes back with its outline.
   *
   * A big report never travels through the backend. Cloud Run caps a request
   * body at 32 MiB and answers past it with a 413 of its own — no JSON, no
   * CORS headers — so the browser sees a bare network failure and the file
   * looks unreadable when nothing ever read it. The FY25-26 consolidated
   * statements are 55MB. Those go straight to storage on a signed URL and the
   * backend is handed the object instead.
   */
  createJob(file: File): Observable<ApiJob> {
    if (file.size > DIRECT_POST_LIMIT_BYTES) return this.uploadToStorage(file);
    const body = new FormData();
    body.append('file', file, file.name);
    return this.http.post<ApiJob>(this.base, body);
  }

  private uploadToStorage(file: File): Observable<ApiJob> {
    return this.http
      .post<ApiUploadUrl>(`${this.base}/upload-url`, {
        filename: file.name,
        sizeBytes: file.size,
      })
      .pipe(
        switchMap(({uploadUrl, gcsUri}) =>
          this.http
            .put(uploadUrl, file, {
              // The URL is signed for this exact content type; the browser's
              // own guess for a .docx is sometimes empty, which would not
              // match the signature.
              headers: new HttpHeaders({'Content-Type': DOCX_MIME}),
            })
            .pipe(
              switchMap(() =>
                this.http.post<ApiJob>(`${this.base}/finalize-upload`, {
                  gcsUri,
                  filename: file.name,
                }),
              ),
            ),
        ),
      );
  }

  reuseEstimate(
    jobId: string,
    targetMarket: string,
  ): Observable<ApiReuseEstimate> {
    return this.http.get<ApiReuseEstimate>(
      `${this.base}/${jobId}/reuse-estimate`,
      {
        params: new HttpParams().set('target_market', targetMarket),
      },
    );
  }

  /** Starts the run in the background; poll {@link getJob} for progress. */
  startTranslation(
    jobId: string,
    targetMarket: string,
    localiseNumbers = false,
    modelId?: string,
  ): Observable<ApiJob> {
    const body: Record<string, string | boolean> = {
      targetMarket,
      localiseNumbers,
    };
    if (modelId) body['modelId'] = modelId;
    return this.http.post<ApiJob>(`${this.base}/${jobId}/translate`, body);
  }

  /**
   * Picks an interrupted run back up: same market and model, and every segment
   * already translated is kept — only the gaps go to the model again.
   */
  resumeTranslation(jobId: string): Observable<ApiJob> {
    return this.http.post<ApiJob>(`${this.base}/${jobId}/resume`, {});
  }

  listSegments(
    jobId: string,
    opts: {
      sectionId?: string;
      reviewFilter?: string;
      statusFilter?: string;
    } = {},
  ): Observable<ApiSegment[]> {
    let params = new HttpParams();
    if (opts.sectionId) params = params.set('section_id', opts.sectionId);
    if (opts.reviewFilter)
      params = params.set('review_filter', opts.reviewFilter);
    if (opts.statusFilter)
      params = params.set('status_filter', opts.statusFilter);
    return this.http.get<ApiSegment[]>(`${this.base}/${jobId}/segments`, {
      params,
    });
  }

  approveSection(
    jobId: string,
    sectionId: string,
  ): Observable<{approved: number; blocked: number}> {
    return this.http.post<{approved: number; blocked: number}>(
      `${this.base}/${jobId}/sections/${encodeURIComponent(sectionId)}/approve`,
      {},
    );
  }

  updateSegment(
    jobId: string,
    segIndex: number,
    patch: {translation?: string; status?: 'translated' | 'approved'},
  ): Observable<ApiSegment> {
    return this.http.patch<ApiSegment>(
      `${this.base}/${jobId}/segments/${segIndex}`,
      patch,
    );
  }

  retranslateSegment(
    jobId: string,
    segIndex: number,
    instruction?: string,
  ): Observable<ApiSegment> {
    return this.http.post<ApiSegment>(
      `${this.base}/${jobId}/segments/${segIndex}/retranslate`,
      {instruction: instruction || null},
    );
  }

  /**
   * Replays the quality checks over the stored translations — no model call,
   * so changing the notation costs nothing but the round trip.
   */
  recheck(jobId: string, localiseNumbers?: boolean): Observable<ApiRecheck> {
    return this.http.post<ApiRecheck>(`${this.base}/${jobId}/recheck`, {
      localiseNumbers: localiseNumbers ?? null,
    });
  }

  /** The translated .docx, as a blob so the browser can save it. */
  exportDocx(jobId: string): Observable<HttpResponseBlob> {
    return this.http.post(
      `${this.base}/${jobId}/export`,
      {},
      {
        observe: 'response',
        responseType: 'blob',
      },
    ) as unknown as Observable<HttpResponseBlob>;
  }
}

/** Minimal shape we need from the export response (body + filename header). */
export interface HttpResponseBlob {
  body: Blob | null;
  headers: {get(name: string): string | null};
}
