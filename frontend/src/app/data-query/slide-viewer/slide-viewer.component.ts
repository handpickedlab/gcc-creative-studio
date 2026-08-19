/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {
  Component,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
} from '@angular/core';
import {ResearchLibraryService} from '../../services/research-library.service';

export interface SlideSource {
  claim_id: number;
  document_id: number;
  document: string;
  page: number;
  statement?: string;
  period?: string | null;
  source_citation?: string | null;
}

/**
 * Lightbox showing the original rendered page behind a cited claim.
 * The image endpoint requires auth, so the image is fetched as a blob via
 * HttpClient (interceptor applies) and shown through an object URL.
 */
@Component({
  selector: 'app-slide-viewer',
  templateUrl: './slide-viewer.component.html',
  styleUrls: ['./slide-viewer.component.scss'],
})
export class SlideViewerComponent implements OnChanges, OnDestroy {
  @Input() source: SlideSource | null = null;
  @Output() closed = new EventEmitter<void>();

  imageUrl: string | null = null;
  loading = false;
  failed = false;

  constructor(private service: ResearchLibraryService) {}

  ngOnChanges(): void {
    this.reset();
    if (!this.source) return;
    this.loading = true;
    this.service.pageImage(this.source.document_id, this.source.page).subscribe({
      next: blob => {
        this.imageUrl = URL.createObjectURL(blob);
        this.loading = false;
      },
      error: () => {
        this.failed = true;
        this.loading = false;
      },
    });
  }

  ngOnDestroy(): void {
    this.reset();
  }

  close(): void {
    this.closed.emit();
  }

  private reset(): void {
    if (this.imageUrl) {
      URL.revokeObjectURL(this.imageUrl);
      this.imageUrl = null;
    }
    this.loading = false;
    this.failed = false;
  }
}
