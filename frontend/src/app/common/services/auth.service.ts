/**
 * Copyright 2025 Google LLC
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

import {Injectable, PLATFORM_ID, inject} from '@angular/core';
import {Router} from '@angular/router';
import {UserModel, UserRolesEnum} from '../models/user.model';
import {HttpClient, HttpHeaders, HttpErrorResponse} from '@angular/common/http';
import {environment} from '../../../environments/environment';
import {Auth, IdTokenResult} from '@angular/fire/auth';
import {UserService} from '../services/user.service';
import {
  GoogleAuthProvider,
  signInWithPopup,
  UserCredential,
} from '@angular/fire/auth';
import {Observable, Subject, from, throwError, of} from 'rxjs';
import {catchError, tap, map, switchMap} from 'rxjs/operators';
import {isPlatformBrowser} from '@angular/common';
import {SettingsService} from '../../services/settings.service';

// Declare the 'google' global object from the Google Identity Services script
declare const google: any;

const FIREBASE_SESSION_KEY = 'firebase_session';
const USER_DETAILS = 'USER_DETAILS';
const LOGIN_ROUTE = '/login';

interface FirebaseSession {
  token: string;
  expiry: number; // Expiration timestamp in milliseconds
}

@Injectable({
  providedIn: 'root',
})
export class AuthService {
  private readonly auth: Auth = inject(Auth);
  private platformId = inject(PLATFORM_ID);
  private readonly provider: GoogleAuthProvider = new GoogleAuthProvider();

  // Store token temporarily in memory for the session
  private currentOAuthAccessToken: string | null = null;
  private firebaseIdToken: string | null = null; // To store the Firebase token for the test
  private firebaseTokenExpiry: number | null = null; // To store token expiration time (in ms)

  // Emits when the One Tap / FedCM prompt could not be shown (third-party
  // sign-in disabled, One Tap cooldown, no active Google session, ...). The
  // login component listens and reveals the rendered Google sign-in button as
  // a popup-based fallback that does not depend on third-party cookies.
  readonly loginPromptSuppressed$ = new Subject<void>();

  constructor(
    private router: Router,
    private httpClient: HttpClient,
    private userService: UserService,
    private settingsService: SettingsService,
  ) {
    this.provider.setCustomParameters({
      // Set custom params for the provider
      prompt: 'select_account',
    });
    this.loadSessionFromStorage();
  }

  /**
   * A test sign-in method to get a Google ID token compatible with Firebase.
   *
   * @returns An Observable that emits the Firebase-compatible ID token.
   */
  signInWithGoogleFirebase(): Observable<string> {
    return from(signInWithPopup(this.auth, this.provider)).pipe(
      // Step 1: Get the Firebase ID token from the successful sign-in.
      switchMap((userCredential: UserCredential) => {
        if (!userCredential.user) {
          return throwError(
            () => new Error('Firebase user not found after sign-in.'),
          );
        }
        return from(userCredential.user.getIdTokenResult());
      }),
      // Step 2: Save the session and sync with the backend.
      switchMap((idTokenResult: IdTokenResult) => {
        const token = idTokenResult.token;
        const expirationTime = Date.parse(idTokenResult.expirationTime);

        // Save session details to memory and local storage.
        this.firebaseIdToken = token;
        this.firebaseTokenExpiry = expirationTime;
        const session: FirebaseSession = {token, expiry: expirationTime};
        localStorage.setItem(FIREBASE_SESSION_KEY, JSON.stringify(session));

        // Call the backend to get or create the user profile.
        return this.syncUserWithBackend$(token).pipe(
          switchMap(() => from(this.settingsService.loadSettings())),
          map(() => token), // Pass the token along for the final result.
        );
      }),
      catchError((error: any) => {
        console.error('An error occurred during the sign-in process:', error);
        return throwError(
          () => new Error(`Sign-in failed. Please try again. ${error}`),
        );
      }),
    );
  }

  /**
   * Asynchronously gets a valid Firebase token.
   * 1. Checks for a valid, non-expired token in memory/cache.
   * 2. If expired or missing, attempts a silent refresh.
   * 3. If silent refresh fails, it emits an error, signaling a required re-login.
   */
  getValidFirebaseToken$(): Observable<string> {
    // First, check our own session info which is loaded from localStorage.
    // This is synchronous and tells us if we have a valid, non-expired token.
    if (!this.isLoggedIn()) {
      return throwError(
        () => new Error('User session is not valid or has expired. 1'),
      );
    }

    // If we have a valid session, check if the Firebase Auth instance is ready.
    const currentUser = this.auth.currentUser;
    if (currentUser) {
      // Ideal case: Auth is ready, so we can force a token refresh to ensure it's fresh.
      return from(currentUser.getIdToken(true)).pipe(
        tap((token: string) => {
          // Update the in-memory cache and localStorage with the refreshed token info.
          const payload = JSON.parse(atob(token.split('.')[1]));
          const expiry = payload.exp * 1000;

          this.firebaseIdToken = token;
          this.firebaseTokenExpiry = expiry;

          const session: FirebaseSession = {token, expiry};
          localStorage.setItem(FIREBASE_SESSION_KEY, JSON.stringify(session));
        }),
      );
    }

    // Fallback case: The Firebase Auth instance is not yet initialized, but we
    // have a valid token from localStorage. We can use this for the current
    // request. The next request will likely hit the ideal case above.
    return of(this.firebaseIdToken!);
  }

  /**
   * A test sign-in method to get a Google ID token compatible with Identity Platform.
   *
   * @returns An Observable that emits the Identity Platform-compatible ID token.
   */
  signInForGoogleIdentityPlatform(): Observable<string> {
    return this.promptForIdentityPlatformToken$().pipe(
      switchMap(idToken => {
        const payload = JSON.parse(atob(idToken.split('.')[1]));
        const userEmail = payload.email?.toLowerCase();

        // If allowed, proceed to save session and return token
        this.firebaseIdToken = idToken;
        this.firebaseTokenExpiry = payload.exp * 1000;

        const session: FirebaseSession = {
          token: idToken,
          expiry: this.firebaseTokenExpiry,
        };
        localStorage.setItem(FIREBASE_SESSION_KEY, JSON.stringify(session));

        // Call the backend to get or create the user profile.
        return this.syncUserWithBackend$(idToken).pipe(
          switchMap(() => from(this.settingsService.loadSettings())),
          map(() => idToken), // Pass the token along for the final result.
        );
      }),
    );
  }

  private promptForIdentityPlatformToken$(): Observable<string> {
    const GOOGLE_CLIENT_ID = environment.GOOGLE_CLIENT_ID;

    return new Observable<string>(observer => {
      if (typeof google === 'undefined') {
        return observer.error(
          new Error(
            'Google Identity Services script not loaded. Add it to index.html',
          ),
        );
      }

      let settled = false;
      let fallbackShown = false;

      const revealFallback = () => {
        clearTimeout(fallbackTimeout);
        if (settled || fallbackShown) return;
        fallbackShown = true;
        this.loginPromptSuppressed$.next();
      };

      // Safety net: if neither a credential nor a prompt-moment notification
      // arrives (some browsers stay silent when the prompt is blocked), reveal
      // the button fallback so the user is never stuck on a spinner.
      const fallbackTimeout = setTimeout(revealFallback, 10000);

      try {
        google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          // FedCM is the browser-native sign-in mechanism that works even when
          // third-party cookies are blocked (Chrome's phase-out). Without it,
          // One Tap silently fails on those browsers.
          use_fedcm_for_prompt: true,
          callback: (response: any) => {
            clearTimeout(fallbackTimeout);
            const idToken = response?.credential;
            if (idToken) {
              settled = true;
              observer.next(idToken);
              observer.complete();
            } else if (!settled) {
              settled = true;
              observer.error(
                new Error(
                  'Google Sign-In response did not contain a credential.',
                ),
              );
            }
          },
        });

        // Show the One Tap / FedCM prompt for a fast, one-click sign-in. When
        // the browser suppresses it (third-party sign-in disabled, One Tap
        // cooldown, no active Google session, dismissed) we do NOT error out —
        // instead we surface the rendered Google button fallback.
        google.accounts.id.prompt((notification: any) => {
          try {
            const suppressed =
              (typeof notification.isNotDisplayed === 'function' &&
                notification.isNotDisplayed()) ||
              (typeof notification.isSkippedMoment === 'function' &&
                notification.isSkippedMoment()) ||
              (typeof notification.isDismissedMoment === 'function' &&
                notification.isDismissedMoment());
            if (suppressed) {
              revealFallback();
            }
          } catch {
            // In FedCM mode some moment methods are unsupported; fall back.
            revealFallback();
          }
        });
      } catch (error) {
        console.error(
          'Error during Google Identity Platform sign-in initialization:',
          error,
        );
        revealFallback();
      }
    });
  }

  /**
   * Renders the official Google sign-in button into the given container using
   * the callback registered by {@link promptForIdentityPlatformToken$}'s
   * `google.accounts.id.initialize`. This popup-based flow yields the same
   * Google ID token and works without third-party cookies, so it is the
   * fallback when One Tap / FedCM is unavailable.
   */
  renderGoogleSignInButton(container: HTMLElement): void {
    if (typeof google === 'undefined' || !container) return;
    container.replaceChildren();
    google.accounts.id.renderButton(container, {
      type: 'standard',
      theme: 'filled_blue',
      size: 'large',
      text: 'signin_with',
      shape: 'pill',
      logo_alignment: 'center',
    });
  }

  /**
   * Asynchronously gets a valid Identity Platform token.
   * 1. Checks for a valid, non-expired token in memory/cache.
   * 2. If expired or missing, attempts a silent refresh.
   * 3. If silent refresh fails, it emits an error, signaling a required re-login.
   */
  getValidIdentityPlatformToken$(): Observable<string> {
    // First, check our own session info which is loaded from localStorage.
    // This is synchronous and tells us if we have a valid, non-expired token.
    if (!this.isLoggedIn()) {
      return of();
    }

    // Fallback case: The Firebase Auth instance is not yet initialized, but we
    // have a valid token from localStorage. We can use this for the current
    // request. The next request will likely hit the ideal case above.
    return of(this.firebaseIdToken!);
  }

  private syncUserWithBackend$(token: string): Observable<UserModel> {
    const headers = new HttpHeaders().set('Authorization', `Bearer ${token}`);
    return this.httpClient
      .get<UserModel>(`${environment.backendURL}/users/me`, {headers})
      .pipe(
        tap((userDetails: UserModel) => {
          // The backend is the source of truth. Save the returned profile to local storage.
          localStorage.setItem(USER_DETAILS, JSON.stringify(userDetails));
          console.log('User profile successfully synced with backend.');
        }),
        catchError((error: HttpErrorResponse) => {
          console.error('Failed to sync user with backend', error);
          // This is a critical error, so we should propagate it.
          return throwError(
            () =>
              new Error(
                error?.error?.detail ||
                  `Could not synchronize user profile with the server. ${error?.error?.detail}`,
              ),
          );
        }),
      );
  }

  async logout(route: string = LOGIN_ROUTE) {
    this.settingsService.reset();
    return this.auth
      .signOut()
      .then(() => {
        this.currentOAuthAccessToken = null; // Clear stored token on logout
        // Clear Firebase session data
        this.firebaseIdToken = null;
        this.firebaseTokenExpiry = null;
        localStorage.removeItem(FIREBASE_SESSION_KEY);
        localStorage.removeItem(USER_DETAILS);
        localStorage.removeItem('showTooltip');
        void this.router.navigateByUrl(route);
      })
      .catch(e => {
        console.error('Sign Out Error', e);
        this.settingsService.reset();
        localStorage.removeItem(FIREBASE_SESSION_KEY);
        localStorage.removeItem(USER_DETAILS);
        localStorage.removeItem('showTooltip');
        void this.router.navigate([LOGIN_ROUTE]);
      });
  }

  isLoggedIn() {
    if (!isPlatformBrowser(this.platformId)) return false;

    // Check if the in-memory token is valid
    const now = Date.now();
    const isTokenValid = !!(
      this.firebaseIdToken &&
      this.firebaseTokenExpiry &&
      this.firebaseTokenExpiry > now
    );

    // The public, token-gated translator feedback page (/feedback/:token) is
    // intentionally reachable without a session. Never bounce it to /login.
    // Use window.location (reliable during deep-link bootstrap, before the
    // Angular router URL has settled) rather than this.router.url.
    const onPublicRoute =
      isPlatformBrowser(this.platformId) &&
      window.location.pathname.startsWith('/feedback/');

    if (!isTokenValid && this.router.url !== LOGIN_ROUTE && !onPublicRoute) {
      void this.router.navigate([LOGIN_ROUTE]);
    }

    return isTokenValid;
  }

  private loadSessionFromStorage(): void {
    if (!isPlatformBrowser(this.platformId)) return;

    const sessionStr = localStorage.getItem(FIREBASE_SESSION_KEY);
    if (sessionStr) {
      const session: FirebaseSession = JSON.parse(sessionStr);
      // Check if the stored session is still valid
      if (session.expiry > Date.now()) {
        this.firebaseIdToken = session.token;
        this.firebaseTokenExpiry = session.expiry;
      } else {
        // If expired, remove it from storage.
        localStorage.removeItem(FIREBASE_SESSION_KEY);
      }
    }
  }

  isUserLoggedIn() {
    if (!isPlatformBrowser(this.platformId)) return false;

    const isUserLoggedIn = localStorage.getItem(FIREBASE_SESSION_KEY) !== null;
    return isUserLoggedIn;
  }

  isUserAdmin() {
    if (!isPlatformBrowser(this.platformId)) return false;

    const user_role = this.userService.getUserDetails()?.roles;
    return user_role?.includes(UserRolesEnum.ADMIN) || false;
  }

  isUserWorkflows() {
    if (!isPlatformBrowser(this.platformId)) return false;

    const user_role = this.userService.getUserDetails()?.roles;
    return user_role?.includes(UserRolesEnum.WORKFLOWS) || false;
  }

  getToken() {
    return this.firebaseIdToken;
  }

  setOAuthAccessToken(token: string | null): void {
    this.currentOAuthAccessToken = token;
  }

  getOAuthAccessToken(): string | null {
    // Renamed from getAccessToken for clarity
    return this.currentOAuthAccessToken;
  }

  /**
   * Retrieves the currently stored access token.
   */
  getAccessToken(): string | null {
    // Note: Tokens expire (usually after 1 hour).
    // A robust implementation would check expiry or refresh the token.
    // Firebase Auth automatically handles ID token refresh, but OAuth access token
    // refresh requires re-authentication or more complex flows not covered here.
    // For a simple deploy button click, getting a fresh token on sign-in might suffice.
    return this.currentOAuthAccessToken;
  }
}
