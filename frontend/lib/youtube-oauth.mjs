/** @typedef {{ kind: "success" | "error" | "info", className: string, role: "alert" | "status", message: string, guideStep?: number }} OAuthFeedback */

const success = {
  kind: "success",
  className: "notice notice-success accounts-oauth-feedback",
  role: "status",
  message: "Channel berhasil dihubungkan dan identitasnya diterima dari backend.",
};

const info = {
  kind: "info",
  className: "notice notice-info accounts-oauth-feedback",
  role: "status",
  message: "Koneksi YouTube dibatalkan. Belum ada channel yang ditambahkan.",
};

const errors = {
  oauth_state_invalid: {
    guideStep: 3,
    message: "Verifikasi keamanan OAuth gagal atau kedaluwarsa. Mulai Hubungkan YouTube lagi dari halaman ini; state dan cookie browser harus cocok.",
  },
  state_error: {
    guideStep: 3,
    message: "Verifikasi keamanan OAuth gagal atau kedaluwarsa. Mulai Hubungkan YouTube lagi dari halaman ini; state dan cookie browser harus cocok.",
  },
  oauth_state_storage_failed: {
    guideStep: 3,
    message: "Backend gagal memeriksa status keamanan OAuth. Tidak ada koneksi yang dibuat. Periksa database lokal lalu coba lagi.",
  },
  oauth_google_denied: {
    guideStep: 2,
    message: "Google tidak memberikan izin OAuth. Tambahkan akun ini ke Test Users bila aplikasi masih Testing, lalu setujui izin yang diminta.",
  },
  oauth_error: {
    guideStep: 2,
    message: "Google tidak menyelesaikan izin OAuth. Jika aplikasi masih Testing, pastikan akun ada di Test Users, lalu coba lagi.",
  },
  oauth_response_invalid: {
    guideStep: 3,
    message: "Respons Google tidak berisi hasil persetujuan yang dapat diproses. Mulai koneksi kembali.",
  },
  oauth_redirect_uri_mismatch: {
    guideStep: 3,
    message: "Callback URL saat penukaran kode berbeda dari Google Cloud. Samakan Authorized redirect URI dengan Callback URL Klipnara.",
  },
  oauth_client_rejected: {
    guideStep: 4,
    message: "Google menolak OAuth Client. Periksa Client ID, Client Secret, dan tipe Web application pada environment backend.",
  },
  oauth_client_not_configured: {
    guideStep: 4,
    message: "OAuth Client backend belum lengkap. Atur Client ID dan Client Secret di environment backend, lalu muat ulang backend.",
  },
  oauth_code_rejected: {
    guideStep: 5,
    message: "Google menolak authorization code karena kedaluwarsa atau sudah dipakai. Mulai koneksi baru; jangan muat ulang callback.",
  },
  oauth_token_exchange_failed: {
    guideStep: 4,
    message: "Google gagal menukar authorization code. Coba lagi; periksa koneksi internet dan status OAuth Client.",
  },
  oauth_scope_insufficient: {
    guideStep: 2,
    message: "Izin belum lengkap. Klipnara memerlukan youtube.upload untuk upload dan youtube.readonly untuk mengenali channel. Hubungkan ulang dan setujui keduanya.",
  },
  youtube_channel_not_found: {
    guideStep: 5,
    message: "Akun Google ini tidak menyediakan channel YouTube untuk Klipnara. Pilih akun Google yang memiliki channel YouTube.",
  },
  youtube_multiple_channels: {
    guideStep: 5,
    message: "Google mengembalikan beberapa channel. Klipnara tidak memilih channel secara otomatis; gunakan akun/grant yang menampilkan satu channel.",
  },
  youtube_api_failed: {
    guideStep: 1,
    message: "YouTube gagal memverifikasi channel. Periksa YouTube Data API v3, kuota, akses akun, lalu coba lagi.",
  },
  oauth_refresh_token_missing: {
    guideStep: 5,
    message: "Google tidak memberikan refresh token, jadi channel tidak disimpan. Cabut akses Klipnara dari Google Account lalu hubungkan dan setujui ulang.",
  },
  oauth_token_storage_failed: {
    guideStep: 4,
    message: "Channel terverifikasi, tetapi token tidak dapat disimpan dengan aman. Koneksi belum dibuat. Periksa Windows user profile dan penyimpanan lokal, lalu coba lagi.",
  },
  oauth_connection_failed: {
    guideStep: 5,
    message: "Koneksi gagal pada tahap yang belum teridentifikasi. Perbarui backend/frontend dan coba lagi; backend mencatat tipe error serta lokasi kode tanpa credential. Cek ulang status channel sebelum retry.",
  },
  error: {
    guideStep: 5,
    message: "Backend lama melaporkan kegagalan OAuth tanpa detail. Muat ulang backend/frontend agar kode error spesifik aktif, lalu coba lagi.",
  },
};

/** @param {string} result @returns {OAuthFeedback} */
export function youtubeOAuthFeedback(result) {
  if (result === "connected") return success;
  if (result === "analytics_enabled") return { ...success, message: "Izin YouTube Analytics aktif untuk channel terverifikasi ini. Publishing permission tetap dipertahankan." };
  if (result === "connected_analytics_scope_missing") return {
    kind: "info", className: "notice notice-info accounts-oauth-feedback", role: "status",
    message: "Channel terhubung. Izin upload dan identitas tersimpan; metrik Analytics belum aktif. Aktifkan Analytics pada kartu channel.",
  };
  if (result === "cancelled" || result === "oauth_cancelled") return info;

  const analyticsErrors = {
    analytics_scope_missing: { guideStep: 2, message: "Google tidak memberikan yt-analytics.readonly. Izin channel yang sudah ada tetap dipertahankan; coba Aktifkan Analytics lagi dan setujui akses baca Analytics." },
    oauth_scope_verification_failed: { guideStep: 2, message: "Google tidak mengembalikan scope yang dapat diverifikasi. Kredensial tersimpan tidak diubah; mulai consent lagi setelah memeriksa konfigurasi OAuth." },
    oauth_scope_downgrade_blocked: { guideStep: 2, message: "Google mengembalikan izin lebih sempit. Kredensial channel lama tetap dipakai; ulangi consent tanpa mencabut izin upload atau channel." },
    oauth_account_unavailable: { guideStep: 5, message: "Channel berubah status saat consent dimulai. Verifikasi atau hubungkan ulang channel, lalu aktifkan Analytics." },
    youtube_channel_mismatch: { guideStep: 5, message: "Google mengembalikan channel berbeda. Koneksi lama tidak diubah; mulai consent dari kartu channel yang benar." },
  };
  const failure = Object.prototype.hasOwnProperty.call(analyticsErrors, result) ? analyticsErrors[result] : Object.prototype.hasOwnProperty.call(errors, result) ? errors[result] : {
    guideStep: 4,
    message: "Koneksi YouTube gagal pada tahap yang tidak dikenali. Muat ulang backend/frontend dan coba lagi; periksa log lokal jika berulang.",
  };
  return {
    kind: "error",
    className: "notice notice-error accounts-oauth-feedback",
    role: "alert",
    ...failure,
  };
}
