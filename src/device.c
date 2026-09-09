// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/device.h"

#include <string.h>

#define HPLJ_IDENTITY_SIZE 256U

static bool hplj_identity_field(const char *identity, const char *name,
                                const char **value, size_t *value_length) {
  size_t name_length = strlen(name);
  const char *field = identity;
  while (*field != '\0') {
    const char *end = strchr(field, ';');
    if (end == NULL) {
      return false;
    }
    const char *colon = memchr(field, ':', (size_t)(end - field));
    if (colon != NULL && (size_t)(colon - field) == name_length &&
        memcmp(field, name, name_length) == 0) {
      *value = colon + 1;
      *value_length = (size_t)(end - (colon + 1));
      return true;
    }
    field = end + 1;
  }
  return false;
}

static bool hplj_field_equals(const char *identity, const char *name,
                              const char *expected) {
  const char *value;
  size_t value_length;
  return hplj_identity_field(identity, name, &value, &value_length) &&
         strlen(expected) == value_length && memcmp(value, expected, value_length) == 0;
}

static bool hplj_exact_reference_identity(const char *identity) {
  bool exact_manufacturer = hplj_field_equals(identity, "MFG", "Hewlett-Packard") ||
                            hplj_field_equals(identity, "MFG", "HP");
  return exact_manufacturer &&
         hplj_field_equals(identity, "MDL", "HP LaserJet 1020");
}

static bool hplj_read_firmware_version(const char *identity,
                                       char version[HPLJ_FIRMWARE_VERSION_SIZE]) {
  const char *value;
  size_t value_length;
  if (!hplj_identity_field(identity, "FWVER", &value, &value_length) ||
      value_length == 0 || value_length >= HPLJ_FIRMWARE_VERSION_SIZE) {
    version[0] = '\0';
    return false;
  }
  memcpy(version, value, value_length);
  version[value_length] = '\0';
  return true;
}

static struct hplj_device_result hplj_failure(enum hplj_error_category category,
                                              enum hplj_retry_safety retry,
                                              enum hplj_human_action action,
                                              const char *detail, size_t bytes_transferred,
                                              unsigned int attempts) {
  return (struct hplj_device_result){
      .error = hplj_error_make(category, retry, action, detail),
      .bytes_transferred = bytes_transferred,
      .attempts = attempts};
}

static struct hplj_device_result hplj_success(size_t bytes_transferred,
                                              unsigned int attempts) {
  return hplj_failure(HPLJ_ERROR_NONE, HPLJ_RETRY_SAFE_AUTOMATIC, HPLJ_ACTION_NONE,
                      "completed", bytes_transferred, attempts);
}

static void hplj_release(struct hplj_device *device) {
  if (device->opened && device->ops.release != NULL) {
    device->ops.release(device->ops.context);
  }
  device->opened = false;
}

static struct hplj_device_result hplj_connect_once(struct hplj_device *device,
                                                    unsigned int attempt) {
  struct hplj_usb_descriptor descriptor = {0};
  char identity[HPLJ_IDENTITY_SIZE];
  size_t identity_length = 0;
  enum hplj_error_category category =
      device->ops.discover(device->ops.context, &descriptor);
  if (category != HPLJ_ERROR_NONE) {
    return hplj_failure(category, HPLJ_RETRY_SAFE_AUTOMATIC,
                        HPLJ_ACTION_RECONNECT_PRINTER,
                        "reference printer discovery failed", 0, attempt);
  }
  if (descriptor.vendor_id != HPLJ_REFERENCE_VENDOR_ID ||
      descriptor.product_id != HPLJ_REFERENCE_PRODUCT_ID) {
    device->state = HPLJ_DEVICE_UNSUPPORTED;
    return hplj_failure(HPLJ_ERROR_UNSUPPORTED_DEVICE, HPLJ_RETRY_EXPLICIT,
                        HPLJ_ACTION_RECONNECT_PRINTER,
                        "USB descriptor is not the reference printer", 0, attempt);
  }
  category = device->ops.open(device->ops.context);
  if (category != HPLJ_ERROR_NONE) {
    return hplj_failure(category, HPLJ_RETRY_SAFE_AUTOMATIC,
                        HPLJ_ACTION_RECONNECT_PRINTER,
                        "could not open the reference printer", 0, attempt);
  }
  device->opened = true;
  category = device->ops.claim_interface(device->ops.context);
  if (category != HPLJ_ERROR_NONE) {
    hplj_release(device);
    return hplj_failure(category, HPLJ_RETRY_SAFE_AUTOMATIC,
                        HPLJ_ACTION_RECONNECT_PRINTER,
                        "could not claim printer interface", 0, attempt);
  }
  category = device->ops.read_identity(device->ops.context, identity, sizeof(identity),
                                       &identity_length);
  if (category != HPLJ_ERROR_NONE) {
    hplj_release(device);
    return hplj_failure(category, HPLJ_RETRY_SAFE_AUTOMATIC,
                        HPLJ_ACTION_RECONNECT_PRINTER,
                        "could not read IEEE 1284 identity", 0, attempt);
  }
  if (identity_length >= sizeof(identity) || identity[identity_length] != '\0') {
    hplj_release(device);
    return hplj_failure(HPLJ_ERROR_DEVICE_PROTOCOL, HPLJ_RETRY_EXPLICIT,
                        HPLJ_ACTION_RECONNECT_PRINTER,
                        "malformed IEEE 1284 identity", 0, attempt);
  }
  if (!hplj_exact_reference_identity(identity)) {
    hplj_release(device);
    device->state = HPLJ_DEVICE_UNSUPPORTED;
    return hplj_failure(HPLJ_ERROR_UNSUPPORTED_DEVICE, HPLJ_RETRY_EXPLICIT,
                        HPLJ_ACTION_RECONNECT_PRINTER,
                        "IEEE 1284 identity is not the reference printer", 0, attempt);
  }
  device->state = hplj_read_firmware_version(identity, device->firmware_version)
                      ? HPLJ_DEVICE_FIRMWARE_PRESENT
                      : HPLJ_DEVICE_PRE_FIRMWARE;
  return hplj_success(0, attempt);
}

void hplj_device_init(struct hplj_device *device, const struct hplj_device_ops *ops) {
  device->state = HPLJ_DEVICE_DISCONNECTED;
  device->ops = *ops;
  device->opened = false;
  device->firmware_version[0] = '\0';
}

struct hplj_device_result hplj_device_connect(struct hplj_device *device) {
  if (device->state != HPLJ_DEVICE_DISCONNECTED) {
    return hplj_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
                        "connect requires a disconnected device", 0, 0);
  }
  struct hplj_device_result result = {0};
  for (unsigned int attempt = 1; attempt <= HPLJ_MAX_AUTOMATIC_ATTEMPTS; attempt++) {
    result = hplj_connect_once(device, attempt);
    if (result.error.category == HPLJ_ERROR_NONE ||
        result.error.category == HPLJ_ERROR_UNSUPPORTED_DEVICE ||
        result.error.category == HPLJ_ERROR_DEVICE_PROTOCOL) {
      return result;
    }
  }
  result.error.retry = HPLJ_RETRY_EXPLICIT;
  device->state = HPLJ_DEVICE_DISCONNECTED;
  return result;
}

static bool hplj_firmware_version_matches(const struct hplj_device *device,
                                          const char *expected_firmware_version) {
  return expected_firmware_version != NULL && expected_firmware_version[0] != '\0' &&
         strcmp(device->firmware_version, expected_firmware_version) == 0;
}

static struct hplj_device_result hplj_verify_post_upload(
    struct hplj_device *device, const char *expected_firmware_version,
    unsigned int attempt) {
  char identity[HPLJ_IDENTITY_SIZE];
  size_t identity_length = 0;
  enum hplj_error_category category = device->ops.read_identity(
      device->ops.context, identity, sizeof(identity), &identity_length);
  if (category != HPLJ_ERROR_NONE) {
    hplj_release(device);
    device->state = HPLJ_DEVICE_DISCONNECTED;
    return hplj_failure(category, HPLJ_RETRY_SAFE_AUTOMATIC,
                        HPLJ_ACTION_RECONNECT_PRINTER,
                        "firmware identity query failed", 0, attempt);
  }
  if (identity_length >= sizeof(identity) || identity[identity_length] != '\0') {
    hplj_release(device);
    device->state = HPLJ_DEVICE_FIRMWARE_UNVERIFIED;
    return hplj_failure(HPLJ_ERROR_DEVICE_PROTOCOL, HPLJ_RETRY_EXPLICIT,
                        HPLJ_ACTION_POWER_CYCLE_PRINTER,
                        "malformed post-upload IEEE 1284 identity", 0, attempt);
  }
  if (!hplj_exact_reference_identity(identity)) {
    hplj_release(device);
    device->state = HPLJ_DEVICE_UNSUPPORTED;
    return hplj_failure(HPLJ_ERROR_UNSUPPORTED_DEVICE, HPLJ_RETRY_EXPLICIT,
                        HPLJ_ACTION_RECONNECT_PRINTER,
                        "printer identity changed during activation", 0, attempt);
  }
  if (!hplj_read_firmware_version(identity, device->firmware_version)) {
    device->state = HPLJ_DEVICE_PRE_FIRMWARE;
    return hplj_failure(HPLJ_ERROR_FIRMWARE_UNVERIFIED,
                        HPLJ_RETRY_SAFE_AUTOMATIC, HPLJ_ACTION_NONE,
                        "firmware version is not visible yet", 0, attempt);
  }
  if (!hplj_firmware_version_matches(device, expected_firmware_version)) {
    hplj_release(device);
    device->state = HPLJ_DEVICE_FIRMWARE_UNVERIFIED;
    return hplj_failure(HPLJ_ERROR_FIRMWARE_UNVERIFIED, HPLJ_RETRY_EXPLICIT,
                        HPLJ_ACTION_POWER_CYCLE_PRINTER,
                        "post-upload firmware version does not match", 0, attempt);
  }
  device->state = HPLJ_DEVICE_READY;
  return hplj_success(0, attempt);
}

struct hplj_device_result hplj_device_bootstrap_firmware(
    struct hplj_device *device, const unsigned char *firmware, size_t firmware_size,
    const char *expected_firmware_version) {
  if (device->state == HPLJ_DEVICE_READY ||
      device->state == HPLJ_DEVICE_FIRMWARE_PRESENT) {
    if (hplj_firmware_version_matches(device, expected_firmware_version)) {
      device->state = HPLJ_DEVICE_READY;
      return hplj_success(0, 0);
    }
    device->state = HPLJ_DEVICE_FIRMWARE_UNVERIFIED;
    return hplj_failure(HPLJ_ERROR_FIRMWARE_UNVERIFIED, HPLJ_RETRY_EXPLICIT,
                        HPLJ_ACTION_POWER_CYCLE_PRINTER,
                        "loaded firmware version does not match the expected version", 0, 0);
  }
  if (device->state != HPLJ_DEVICE_PRE_FIRMWARE &&
      device->state != HPLJ_DEVICE_AWAITING_FIRMWARE) {
    return hplj_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
                        "firmware bootstrap requires a connected printer", 0, 0);
  }
  if (firmware == NULL || firmware_size == 0) {
    device->state = HPLJ_DEVICE_AWAITING_FIRMWARE;
    return hplj_failure(HPLJ_ERROR_FIRMWARE_MISSING, HPLJ_RETRY_NEVER,
                        HPLJ_ACTION_IMPORT_FIRMWARE,
                        "user-supplied firmware is required", 0, 0);
  }
  if (expected_firmware_version == NULL || expected_firmware_version[0] == '\0') {
    device->state = HPLJ_DEVICE_FIRMWARE_UNVERIFIED;
    return hplj_failure(HPLJ_ERROR_FIRMWARE_UNVERIFIED, HPLJ_RETRY_EXPLICIT,
                        HPLJ_ACTION_POWER_CYCLE_PRINTER,
                        "expected firmware version is required", 0, 0);
  }

  bool upload_completed = false;
  for (unsigned int attempt = 1; attempt <= HPLJ_MAX_AUTOMATIC_ATTEMPTS; attempt++) {
    if (device->state == HPLJ_DEVICE_DISCONNECTED) {
      struct hplj_device_result connected = hplj_connect_once(device, attempt);
      if (connected.error.category != HPLJ_ERROR_NONE) {
        if (connected.error.category == HPLJ_ERROR_UNSUPPORTED_DEVICE ||
            connected.error.category == HPLJ_ERROR_DEVICE_PROTOCOL) {
          return connected;
        }
        continue;
      }
      if (device->state == HPLJ_DEVICE_FIRMWARE_PRESENT) {
        if (hplj_firmware_version_matches(device, expected_firmware_version)) {
          device->state = HPLJ_DEVICE_READY;
          return hplj_success(0, attempt);
        }
        device->state = HPLJ_DEVICE_FIRMWARE_UNVERIFIED;
        return hplj_failure(HPLJ_ERROR_FIRMWARE_UNVERIFIED, HPLJ_RETRY_EXPLICIT,
                            HPLJ_ACTION_POWER_CYCLE_PRINTER,
                            "post-upload firmware version does not match", 0, attempt);
      }
    }

    if (!upload_completed) {
      enum hplj_error_category upload_error =
          device->ops.upload_firmware(device->ops.context, firmware, firmware_size);
      if (upload_error != HPLJ_ERROR_NONE) {
        hplj_release(device);
        device->state = HPLJ_DEVICE_DISCONNECTED;
        continue;
      }
      upload_completed = true;
    }
    struct hplj_device_result verified = hplj_verify_post_upload(
        device, expected_firmware_version, attempt);
    if (verified.error.category == HPLJ_ERROR_NONE ||
        verified.error.retry == HPLJ_RETRY_EXPLICIT) {
      return verified;
    }
  }

  hplj_release(device);
  device->state = upload_completed ? HPLJ_DEVICE_FIRMWARE_UNVERIFIED
                                   : HPLJ_DEVICE_FIRMWARE_TRANSFER_FAILED;
  return hplj_failure(upload_completed ? HPLJ_ERROR_FIRMWARE_UNVERIFIED
                                       : HPLJ_ERROR_FIRMWARE_TRANSFER_FAILED,
                      HPLJ_RETRY_EXPLICIT,
                      upload_completed ? HPLJ_ACTION_POWER_CYCLE_PRINTER
                                       : HPLJ_ACTION_RECONNECT_AND_RETRY_FIRMWARE,
                      upload_completed ? "firmware activation retry limit reached"
                                       : "firmware transfer retry limit reached",
                      0, HPLJ_MAX_AUTOMATIC_ATTEMPTS);
}

static struct hplj_device_result hplj_device_send_attempts(
    struct hplj_device *device, const unsigned char *bytes, size_t byte_count,
    bool cancelled, unsigned int maximum_attempts) {
  if (device->state != HPLJ_DEVICE_READY) {
    return hplj_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
                        "print transfer requires a ready printer", 0, 0);
  }
  if (cancelled) {
    return hplj_failure(HPLJ_ERROR_CANCELLED, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
                        "job was cancelled before transfer", 0, 0);
  }
  if (bytes == NULL || byte_count == 0) {
    return hplj_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
                        "print transfer requires non-empty bytes", 0, 0);
  }

  struct hplj_transfer_result transfer = {0};
  for (unsigned int attempt = 1; attempt <= maximum_attempts; attempt++) {
    transfer = device->ops.write(device->ops.context, bytes, byte_count);
    if (transfer.bytes_transferred > byte_count) {
      device->state = HPLJ_DEVICE_DISCONNECTED;
      hplj_release(device);
      return hplj_failure(HPLJ_ERROR_DEVICE_PROTOCOL, HPLJ_RETRY_EXPLICIT,
                          HPLJ_ACTION_RETRY_JOB,
                          "transport reported an ambiguous print byte count",
                          transfer.bytes_transferred, attempt);
    }
    if (transfer.category == HPLJ_ERROR_NONE &&
        transfer.bytes_transferred == byte_count) {
      return hplj_success(transfer.bytes_transferred, attempt);
    }
    if (transfer.bytes_transferred > 0) {
      device->state = HPLJ_DEVICE_DISCONNECTED;
      hplj_release(device);
      enum hplj_error_category category = transfer.category == HPLJ_ERROR_NONE
                                              ? HPLJ_ERROR_TRANSFER_INCOMPLETE
                                              : transfer.category;
      return hplj_failure(category, HPLJ_RETRY_EXPLICIT, HPLJ_ACTION_RETRY_JOB,
                          "print transfer failed after bytes were sent",
                          transfer.bytes_transferred, attempt);
    }
    if (transfer.category == HPLJ_ERROR_DEVICE_DISCONNECTED ||
        transfer.category == HPLJ_ERROR_DEVICE_PROTOCOL) {
      device->state = HPLJ_DEVICE_DISCONNECTED;
      hplj_release(device);
      return hplj_failure(transfer.category, HPLJ_RETRY_SAFE_AUTOMATIC,
                          HPLJ_ACTION_RECONNECT_PRINTER,
                          "print transfer failed before bytes were sent", 0, attempt);
    }
  }
  return hplj_failure(transfer.category == HPLJ_ERROR_NONE
                          ? HPLJ_ERROR_TRANSFER_INCOMPLETE
                          : transfer.category,
                      HPLJ_RETRY_EXPLICIT, HPLJ_ACTION_RETRY_JOB,
                      "print transfer retry limit reached before bytes were sent", 0,
                      maximum_attempts);
}

struct hplj_device_result hplj_device_send(struct hplj_device *device,
                                           const unsigned char *bytes,
                                           size_t byte_count, bool cancelled) {
  return hplj_device_send_attempts(device, bytes, byte_count, cancelled,
                                   HPLJ_MAX_AUTOMATIC_ATTEMPTS);
}

struct hplj_device_result hplj_device_send_once(struct hplj_device *device,
                                                const unsigned char *bytes,
                                                size_t byte_count,
                                                bool cancelled) {
  return hplj_device_send_attempts(device, bytes, byte_count, cancelled, 1);
}

struct hplj_device_result hplj_device_revalidate(
    struct hplj_device *device, const char *expected_firmware_version) {
  if (device == NULL || device->state != HPLJ_DEVICE_READY || !device->opened) {
    return hplj_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER,
                        HPLJ_ACTION_NONE, "ready printer cannot be revalidated", 0, 0);
  }
  char identity[HPLJ_IDENTITY_SIZE];
  size_t identity_length = 0;
  enum hplj_error_category category = device->ops.read_identity(
      device->ops.context, identity, sizeof(identity), &identity_length);
  if (category != HPLJ_ERROR_NONE || identity_length >= sizeof(identity) ||
      identity[identity_length] != '\0') {
    hplj_device_disconnect(device);
    return hplj_failure(category == HPLJ_ERROR_NONE ? HPLJ_ERROR_DEVICE_PROTOCOL
                                                     : category,
                        HPLJ_RETRY_SAFE_AUTOMATIC,
                        HPLJ_ACTION_RECONNECT_PRINTER,
                        "ready printer identity query failed", 0, 1);
  }
  if (!hplj_exact_reference_identity(identity)) {
    hplj_device_disconnect(device);
    device->state = HPLJ_DEVICE_UNSUPPORTED;
    return hplj_failure(HPLJ_ERROR_UNSUPPORTED_DEVICE, HPLJ_RETRY_EXPLICIT,
                        HPLJ_ACTION_RECONNECT_PRINTER,
                        "ready printer identity changed", 0, 1);
  }
  if (!hplj_read_firmware_version(identity, device->firmware_version)) {
    device->state = HPLJ_DEVICE_PRE_FIRMWARE;
    return hplj_failure(HPLJ_ERROR_FIRMWARE_MISSING,
                        HPLJ_RETRY_SAFE_AUTOMATIC,
                        HPLJ_ACTION_IMPORT_FIRMWARE,
                        "printer power cycle requires firmware", 0, 1);
  }
  if (!hplj_firmware_version_matches(device, expected_firmware_version)) {
    hplj_release(device);
    device->state = HPLJ_DEVICE_FIRMWARE_UNVERIFIED;
    return hplj_failure(HPLJ_ERROR_FIRMWARE_UNVERIFIED,
                        HPLJ_RETRY_EXPLICIT,
                        HPLJ_ACTION_POWER_CYCLE_PRINTER,
                        "ready printer firmware version changed", 0, 1);
  }
  return hplj_success(0, 1);
}

struct hplj_device_result hplj_device_get_status(
    struct hplj_device *device, unsigned int *conditions) {
  if (conditions != NULL) {
    *conditions = HPLJ_DEVICE_CONDITION_NONE;
  }
  if (device == NULL || conditions == NULL ||
      device->state != HPLJ_DEVICE_READY || !device->opened ||
      device->ops.read_status == NULL) {
    return hplj_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER,
                        HPLJ_ACTION_NONE, "printer status is unavailable", 0, 0);
  }
  enum hplj_error_category category =
      device->ops.read_status(device->ops.context, conditions);
  if (category != HPLJ_ERROR_NONE) {
    hplj_device_disconnect(device);
    return hplj_failure(category, HPLJ_RETRY_SAFE_AUTOMATIC,
                        HPLJ_ACTION_RECONNECT_PRINTER,
                        "printer status query failed", 0, 1);
  }
  return hplj_success(0, 1);
}

void hplj_device_disconnect(struct hplj_device *device) {
  hplj_release(device);
  device->firmware_version[0] = '\0';
  device->state = HPLJ_DEVICE_DISCONNECTED;
}

void hplj_device_suspend(struct hplj_device *device) {
  hplj_device_disconnect(device);
}
