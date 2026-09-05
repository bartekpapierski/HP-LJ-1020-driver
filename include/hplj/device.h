// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef HPLJ_DEVICE_H
#define HPLJ_DEVICE_H

#include "hplj/error.h"

#include <stdbool.h>
#include <stddef.h>

enum hplj_device_state {
  HPLJ_DEVICE_DISCONNECTED,
  HPLJ_DEVICE_PRE_FIRMWARE,
  HPLJ_DEVICE_AWAITING_FIRMWARE,
  HPLJ_DEVICE_FIRMWARE_TRANSFER_FAILED,
  HPLJ_DEVICE_FIRMWARE_UNVERIFIED,
  HPLJ_DEVICE_READY,
  HPLJ_DEVICE_UNSUPPORTED,
};

struct hplj_transfer_result {
  enum hplj_error_category category;
  size_t bytes_transferred;
};

struct hplj_device_ops {
  /* All callbacks borrow context. The device owns no hardware handle. */
  enum hplj_error_category (*discover_exact)(void *context);
  enum hplj_error_category (*open)(void *context);
  enum hplj_error_category (*claim_interface)(void *context);
  /*
   * Writes a NUL-terminated IEEE 1284 identity, reports its length excluding
   * the terminator, and rejects output that cannot fit in identity_size.
   */
  enum hplj_error_category (*read_identity)(void *context, char *identity,
                                             size_t identity_size, size_t *identity_length);
  enum hplj_error_category (*upload_firmware)(void *context,
                                              const unsigned char *firmware,
                                              size_t firmware_size);
  struct hplj_transfer_result (*write)(void *context, const unsigned char *bytes,
                                       size_t byte_count);
  void (*release)(void *context);
  void *context;
};

struct hplj_device {
  enum hplj_device_state state;
  struct hplj_device_ops ops;
  bool opened;
};

struct hplj_device_result {
  struct hplj_error error;
  size_t bytes_transferred;
};

void hplj_device_init(struct hplj_device *device, const struct hplj_device_ops *ops);
struct hplj_device_result hplj_device_connect(struct hplj_device *device);
struct hplj_device_result hplj_device_bootstrap_firmware(
    struct hplj_device *device, const unsigned char *firmware, size_t firmware_size);
struct hplj_device_result hplj_device_send(struct hplj_device *device,
                                           const unsigned char *bytes, size_t byte_count,
                                           bool cancelled);
void hplj_device_disconnect(struct hplj_device *device);

#endif
