// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/device.h"

#include <string.h>

static const char *const hplj_identity_prefix = "MFG:HP;MDL:HP LaserJet 1020;";

static bool hplj_has_firmware_version(const char *identity) {
  const char *search = identity;
  const char *marker;
  while ((marker = strstr(search, "FWVER:")) != NULL) {
    const char *version = marker + strlen("FWVER:");
    if ((marker == identity || marker[-1] == ';') && version[0] != '\0' &&
        version[0] != ';' && strchr(version, ';') != NULL) {
      return true;
    }
    search = marker + 1;
  }
  return false;
}

static struct hplj_device_result hplj_failure(enum hplj_error_category category,
                                              enum hplj_retry_safety retry,
                                              enum hplj_human_action action,
                                              const char *detail, size_t bytes_transferred) {
  return (struct hplj_device_result){
      .error = hplj_error_make(category, retry, action, detail),
      .bytes_transferred = bytes_transferred};
}

static struct hplj_device_result hplj_success(size_t bytes_transferred) {
  return hplj_failure(HPLJ_ERROR_NONE, HPLJ_RETRY_SAFE_AUTOMATIC, HPLJ_ACTION_NONE,
                      "completed", bytes_transferred);
}

static void hplj_release(struct hplj_device *device) {
  if (device->opened && device->ops.release != NULL) {
    device->ops.release(device->ops.context);
  }
  device->opened = false;
}

void hplj_device_init(struct hplj_device *device, const struct hplj_device_ops *ops) {
  device->state = HPLJ_DEVICE_DISCONNECTED;
  device->ops = *ops;
  device->opened = false;
}

struct hplj_device_result hplj_device_connect(struct hplj_device *device) {
  char identity[256];
  size_t identity_length = 0;
  if (device->state != HPLJ_DEVICE_DISCONNECTED) {
    return hplj_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
                        "connect requires a disconnected device", 0);
  }
  enum hplj_error_category category = device->ops.discover_exact(device->ops.context);
  if (category != HPLJ_ERROR_NONE) {
    return hplj_failure(category, HPLJ_RETRY_SAFE_AUTOMATIC, HPLJ_ACTION_RECONNECT_PRINTER,
                        "exact reference printer was not discovered", 0);
  }
  category = device->ops.open(device->ops.context);
  if (category != HPLJ_ERROR_NONE) {
    return hplj_failure(category, HPLJ_RETRY_SAFE_AUTOMATIC, HPLJ_ACTION_RECONNECT_PRINTER,
                        "could not open the reference printer", 0);
  }
  device->opened = true;
  category = device->ops.claim_interface(device->ops.context);
  if (category != HPLJ_ERROR_NONE) {
    hplj_release(device);
    return hplj_failure(category, HPLJ_RETRY_SAFE_AUTOMATIC, HPLJ_ACTION_RECONNECT_PRINTER,
                        "could not claim printer interface", 0);
  }
  category = device->ops.read_identity(device->ops.context, identity, sizeof(identity),
                                       &identity_length);
  if (category != HPLJ_ERROR_NONE) {
    hplj_release(device);
    return hplj_failure(category, HPLJ_RETRY_SAFE_AUTOMATIC, HPLJ_ACTION_RECONNECT_PRINTER,
                        "could not read IEEE 1284 identity", 0);
  }
  if (identity_length >= sizeof(identity) || identity[identity_length] != '\0' ||
      strncmp(identity, hplj_identity_prefix, strlen(hplj_identity_prefix)) != 0) {
    hplj_release(device);
    device->state = HPLJ_DEVICE_UNSUPPORTED;
    return hplj_failure(HPLJ_ERROR_DEVICE_PROTOCOL, HPLJ_RETRY_NEVER,
                        HPLJ_ACTION_RECONNECT_PRINTER, "unexpected printer identity", 0);
  }
  device->state = hplj_has_firmware_version(identity) ? HPLJ_DEVICE_READY
                                                       : HPLJ_DEVICE_PRE_FIRMWARE;
  return hplj_success(0);
}

struct hplj_device_result hplj_device_bootstrap_firmware(
    struct hplj_device *device, const unsigned char *firmware, size_t firmware_size) {
  char identity[256];
  size_t identity_length = 0;
  if (device->state == HPLJ_DEVICE_READY) {
    return hplj_success(0);
  }
  if (device->state != HPLJ_DEVICE_PRE_FIRMWARE &&
      device->state != HPLJ_DEVICE_AWAITING_FIRMWARE) {
    return hplj_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
                        "firmware bootstrap requires a connected printer", 0);
  }
  if (firmware == NULL || firmware_size == 0) {
    device->state = HPLJ_DEVICE_AWAITING_FIRMWARE;
    return hplj_failure(HPLJ_ERROR_FIRMWARE_MISSING, HPLJ_RETRY_NEVER,
                        HPLJ_ACTION_IMPORT_FIRMWARE, "user-supplied firmware is required", 0);
  }
  enum hplj_error_category category =
      device->ops.upload_firmware(device->ops.context, firmware, firmware_size);
  if (category != HPLJ_ERROR_NONE) {
    hplj_release(device);
    device->state = HPLJ_DEVICE_FIRMWARE_TRANSFER_FAILED;
    return hplj_failure(HPLJ_ERROR_FIRMWARE_TRANSFER_FAILED, HPLJ_RETRY_EXPLICIT,
                        HPLJ_ACTION_RECONNECT_AND_RETRY_FIRMWARE,
                        "firmware transfer failed", 0);
  }
  category = device->ops.read_identity(device->ops.context, identity, sizeof(identity),
                                       &identity_length);
  if (category != HPLJ_ERROR_NONE || identity_length >= sizeof(identity) ||
      identity[identity_length] != '\0' || !hplj_has_firmware_version(identity)) {
    hplj_release(device);
    device->state = HPLJ_DEVICE_FIRMWARE_UNVERIFIED;
    return hplj_failure(HPLJ_ERROR_FIRMWARE_UNVERIFIED, HPLJ_RETRY_EXPLICIT,
                        HPLJ_ACTION_POWER_CYCLE_PRINTER,
                        "firmware version was not verified", 0);
  }
  device->state = HPLJ_DEVICE_READY;
  return hplj_success(0);
}

struct hplj_device_result hplj_device_send(struct hplj_device *device,
                                           const unsigned char *bytes, size_t byte_count,
                                           bool cancelled) {
  if (device->state != HPLJ_DEVICE_READY) {
    return hplj_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
                        "print transfer requires a ready printer", 0);
  }
  if (cancelled) {
    return hplj_failure(HPLJ_ERROR_CANCELLED, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
                        "job was cancelled before transfer", 0);
  }
  struct hplj_transfer_result transfer =
      device->ops.write(device->ops.context, bytes, byte_count);
  if (transfer.category == HPLJ_ERROR_NONE && transfer.bytes_transferred == byte_count) {
    return hplj_success(transfer.bytes_transferred);
  }
  device->state = HPLJ_DEVICE_DISCONNECTED;
  hplj_release(device);
  enum hplj_retry_safety retry = transfer.bytes_transferred == 0 ? HPLJ_RETRY_SAFE_AUTOMATIC
                                                                  : HPLJ_RETRY_EXPLICIT;
  enum hplj_error_category category = transfer.category == HPLJ_ERROR_NONE
                                          ? HPLJ_ERROR_TRANSFER_INCOMPLETE
                                          : transfer.category;
  return hplj_failure(category, retry, HPLJ_ACTION_RETRY_JOB,
                      "print transfer did not complete", transfer.bytes_transferred);
}

void hplj_device_disconnect(struct hplj_device *device) {
  hplj_release(device);
  device->state = HPLJ_DEVICE_DISCONNECTED;
}
