// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/error.h"

struct hplj_error hplj_error_make(enum hplj_error_category category,
                                  enum hplj_retry_safety retry,
                                  enum hplj_human_action action,
                                  const char *detail) {
  return (struct hplj_error){.category = category, .retry = retry, .action = action,
                             .detail = detail};
}
