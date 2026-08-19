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

import {Component, OnInit} from '@angular/core';
import {MatSnackBar} from '@angular/material/snack-bar';
import {concatMap, from} from 'rxjs';
import {DataQueryService, SheetInfo} from '../../services/data-query.service';
import {handleErrorSnackbar} from '../../utils/handleMessageSnackbar';

/**
 * Dedicated page to view and manage the durably-stored data-query sheets.
 * Uploads survive restarts (raw file in GCS + Postgres catalog), unlike the
 * ephemeral DuckDB warehouse they are loaded into.
 */
@Component({
  selector: 'app-data-sources',
  templateUrl: './data-sources.component.html',
  styleUrls: ['./data-sources.component.scss'],
})
export class DataSourcesComponent implements OnInit {
  sheets: SheetInfo[] = [];
  loading = true;
  uploadsPending = 0;

  constructor(
    private service: DataQueryService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading = true;
    this.service.sheets().subscribe({
      next: s => {
        this.sheets = s;
        this.loading = false;
      },
      error: err => {
        this.loading = false;
        handleErrorSnackbar(this.snackBar, err, 'Sheets');
      },
    });
  }

  onFilesSelected(ev: Event): void {
    const input = ev.target as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    input.value = '';
    if (!files.length) return;

    this.uploadsPending = files.length;
    from(files)
      .pipe(concatMap(file => this.service.upload(file)))
      .subscribe({
        next: () => this.uploadsPending--,
        error: err => {
          this.uploadsPending = 0;
          handleErrorSnackbar(this.snackBar, err, 'Upload');
          this.refresh();
        },
        complete: () => {
          this.uploadsPending = 0;
          this.refresh();
        },
      });
  }

  delete(sheet: SheetInfo): void {
    this.service.deleteSheet(sheet.id).subscribe({
      next: () => (this.sheets = this.sheets.filter(s => s.id !== sheet.id)),
      error: err => handleErrorSnackbar(this.snackBar, err, 'Delete'),
    });
  }

  columnsPreview(sheet: SheetInfo): string {
    const cols = sheet.columns ?? [];
    const head = cols.slice(0, 6).join(', ');
    return cols.length > 6 ? `${head}, +${cols.length - 6} more` : head;
  }
}
