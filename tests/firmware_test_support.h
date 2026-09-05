// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef HPLJ_FIRMWARE_TEST_SUPPORT_H
#define HPLJ_FIRMWARE_TEST_SUPPORT_H

#include "hplj/firmware.h"

struct hplj_firmware_result hplj_firmware_import_synthetic_host_fixture(
    const struct hplj_firmware_import_request *request,
    const struct hplj_firmware_allowlist_entry *allowlist, size_t allowlist_count,
    const struct hplj_firmware_store *store);

#endif
