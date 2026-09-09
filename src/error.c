// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/error.h"

#include <stddef.h>

const char *hplj_error_category_name(enum hplj_error_category category) {
  static const char *names[] = {
      "none",
      "invalid-state",
      "unsupported-device",
      "device-access-denied",
      "device-protocol",
      "device-disconnected",
      "device-timeout",
      "transfer-incomplete",
      "firmware-missing",
      "firmware-affirmation-required",
      "firmware-unsupported",
      "firmware-corrupt",
      "firmware-storage-failed",
      "firmware-transfer-failed",
      "firmware-unverified",
      "raster-invalid",
      "canceled",
      "encoding-failed",
      "queue-unavailable",
      "media-empty",
      "manual-feed-required",
      "cover-open",
      "device-fault",
  };
  _Static_assert(sizeof(names) / sizeof(names[0]) == HPLJ_ERROR_CATEGORY_COUNT,
                 "error category names must remain exhaustive");
  return category >= HPLJ_ERROR_NONE && category < HPLJ_ERROR_CATEGORY_COUNT
             ? names[(size_t)category]
             : "unknown";
}

struct hplj_error hplj_error_make(enum hplj_error_category category,
                                  enum hplj_retry_safety retry,
                                  enum hplj_human_action action,
                                  const char *detail) {
  return (struct hplj_error){.category = category, .retry = retry, .action = action,
                             .detail = detail};
}
