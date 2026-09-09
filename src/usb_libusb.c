// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/usb_libusb.h"

#include <libusb.h>

#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define HPLJ_USB_TIMEOUT_MS 5000U
#define HPLJ_IEEE1284_REQUEST 0U
#define HPLJ_PORT_STATUS_REQUEST 1U
#define HPLJ_PRINTER_CLASS 7U
#define HPLJ_PRINTER_SUBCLASS 1U

struct hplj_libusb_transport {
  libusb_context *context;
  libusb_device *candidate;
  libusb_device_handle *handle;
  int interface_number;
  int alternate_setting;
  uint8_t configuration_value;
  uint8_t configuration_index;
  uint8_t bulk_out_endpoint;
  bool interface_claimed;
};

static enum hplj_error_category hplj_libusb_error(int error) {
  switch (error) {
    case LIBUSB_SUCCESS:
      return HPLJ_ERROR_NONE;
    case LIBUSB_ERROR_TIMEOUT:
      return HPLJ_ERROR_DEVICE_TIMEOUT;
    case LIBUSB_ERROR_NO_DEVICE:
    case LIBUSB_ERROR_NOT_FOUND:
      return HPLJ_ERROR_DEVICE_DISCONNECTED;
    case LIBUSB_ERROR_ACCESS:
    case LIBUSB_ERROR_BUSY:
      return HPLJ_ERROR_DEVICE_ACCESS_DENIED;
    default:
      return HPLJ_ERROR_DEVICE_PROTOCOL;
  }
}

static void hplj_libusb_release(void *context) {
  struct hplj_libusb_transport *transport = context;
  if (transport->handle != NULL && transport->interface_claimed) {
    (void)libusb_release_interface(transport->handle, transport->interface_number);
  }
  transport->interface_claimed = false;
  if (transport->handle != NULL) {
    libusb_close(transport->handle);
    transport->handle = NULL;
  }
  if (transport->candidate != NULL) {
    libusb_unref_device(transport->candidate);
    transport->candidate = NULL;
  }
}

static enum hplj_error_category hplj_libusb_discover(
    void *context, struct hplj_usb_descriptor *descriptor) {
  struct hplj_libusb_transport *transport = context;
  libusb_device **devices = NULL;
  ssize_t count = libusb_get_device_list(transport->context, &devices);
  if (count < 0) {
    return hplj_libusb_error((int)count);
  }
  if (transport->candidate != NULL) {
    libusb_unref_device(transport->candidate);
    transport->candidate = NULL;
  }
  for (ssize_t index = 0; index < count; index++) {
    struct libusb_device_descriptor found;
    if (libusb_get_device_descriptor(devices[index], &found) == LIBUSB_SUCCESS &&
        found.idVendor == HPLJ_REFERENCE_VENDOR_ID &&
        found.idProduct == HPLJ_REFERENCE_PRODUCT_ID) {
      transport->candidate = libusb_ref_device(devices[index]);
      descriptor->vendor_id = found.idVendor;
      descriptor->product_id = found.idProduct;
      break;
    }
  }
  libusb_free_device_list(devices, 1);
  return transport->candidate == NULL ? HPLJ_ERROR_DEVICE_DISCONNECTED
                                      : HPLJ_ERROR_NONE;
}

static enum hplj_error_category hplj_libusb_open(void *context) {
  struct hplj_libusb_transport *transport = context;
  if (transport->candidate == NULL) {
    return HPLJ_ERROR_DEVICE_DISCONNECTED;
  }
  return hplj_libusb_error(libusb_open(transport->candidate, &transport->handle));
}

static enum hplj_error_category hplj_libusb_claim(void *context) {
  struct hplj_libusb_transport *transport = context;
  struct libusb_config_descriptor *configuration = NULL;
  int error = libusb_get_active_config_descriptor(
      libusb_get_device(transport->handle), &configuration);
  if (error != LIBUSB_SUCCESS) {
    return hplj_libusb_error(error);
  }

  bool found = false;
  for (uint8_t interface_index = 0;
       interface_index < configuration->bNumInterfaces && !found;
       interface_index++) {
    const struct libusb_interface *interface = &configuration->interface[interface_index];
    for (int alternate_index = 0; alternate_index < interface->num_altsetting && !found;
         alternate_index++) {
      const struct libusb_interface_descriptor *alternate =
          &interface->altsetting[alternate_index];
      if (alternate->bInterfaceClass != HPLJ_PRINTER_CLASS ||
          alternate->bInterfaceSubClass != HPLJ_PRINTER_SUBCLASS) {
        continue;
      }
      for (uint8_t endpoint_index = 0; endpoint_index < alternate->bNumEndpoints;
           endpoint_index++) {
        const struct libusb_endpoint_descriptor *endpoint =
            &alternate->endpoint[endpoint_index];
        if ((endpoint->bmAttributes & LIBUSB_TRANSFER_TYPE_MASK) ==
                LIBUSB_TRANSFER_TYPE_BULK &&
            (endpoint->bEndpointAddress & LIBUSB_ENDPOINT_DIR_MASK) ==
                LIBUSB_ENDPOINT_OUT) {
          transport->interface_number = alternate->bInterfaceNumber;
          transport->alternate_setting = alternate->bAlternateSetting;
          transport->configuration_value = configuration->bConfigurationValue;
          transport->bulk_out_endpoint = endpoint->bEndpointAddress;
          found = true;
          break;
        }
      }
    }
  }
  libusb_free_config_descriptor(configuration);
  if (!found) {
    return HPLJ_ERROR_DEVICE_PROTOCOL;
  }
  struct libusb_device_descriptor device_descriptor;
  error = libusb_get_device_descriptor(libusb_get_device(transport->handle),
                                       &device_descriptor);
  if (error != LIBUSB_SUCCESS) {
    return hplj_libusb_error(error);
  }
  bool configuration_index_found = false;
  for (uint8_t index = 0; index < device_descriptor.bNumConfigurations; index++) {
    struct libusb_config_descriptor *indexed_configuration = NULL;
    error = libusb_get_config_descriptor(libusb_get_device(transport->handle), index,
                                         &indexed_configuration);
    if (error != LIBUSB_SUCCESS) {
      return hplj_libusb_error(error);
    }
    if (indexed_configuration->bConfigurationValue ==
        transport->configuration_value) {
      transport->configuration_index = index;
      configuration_index_found = true;
    }
    libusb_free_config_descriptor(indexed_configuration);
    if (configuration_index_found) {
      break;
    }
  }
  if (!configuration_index_found) {
    return HPLJ_ERROR_DEVICE_PROTOCOL;
  }
  error = libusb_claim_interface(transport->handle, transport->interface_number);
  if (error != LIBUSB_SUCCESS) {
    return hplj_libusb_error(error);
  }
  transport->interface_claimed = true;
  error = libusb_set_interface_alt_setting(
      transport->handle, transport->interface_number, transport->alternate_setting);
  return hplj_libusb_error(error);
}

static enum hplj_error_category hplj_libusb_identity(
    void *context, char *identity, size_t identity_size, size_t *identity_length) {
  struct hplj_libusb_transport *transport = context;
  unsigned char response[1024];
  uint16_t index = (uint16_t)(((uint16_t)transport->interface_number << 8) |
                              (uint16_t)transport->alternate_setting);
  int transferred = libusb_control_transfer(
      transport->handle,
      LIBUSB_ENDPOINT_IN | LIBUSB_REQUEST_TYPE_CLASS | LIBUSB_RECIPIENT_INTERFACE,
      HPLJ_IEEE1284_REQUEST, transport->configuration_index, index, response,
      sizeof(response), HPLJ_USB_TIMEOUT_MS);
  if (transferred < 0) {
    return hplj_libusb_error(transferred);
  }
  if (transferred < 2) {
    return HPLJ_ERROR_DEVICE_PROTOCOL;
  }
  size_t reported = ((size_t)response[0] << 8) | response[1];
  if (reported < 2 || reported > (size_t)transferred) {
    return HPLJ_ERROR_DEVICE_PROTOCOL;
  }
  size_t payload = reported - 2;
  if (payload + 1 > identity_size || memchr(response + 2, '\0', payload) != NULL) {
    return HPLJ_ERROR_DEVICE_PROTOCOL;
  }
  memcpy(identity, response + 2, payload);
  identity[payload] = '\0';
  *identity_length = payload;
  return HPLJ_ERROR_NONE;
}

static struct hplj_transfer_result hplj_libusb_bulk_write(
    struct hplj_libusb_transport *transport, const unsigned char *bytes,
    size_t byte_count) {
  size_t total = 0;
  while (total < byte_count) {
    int chunk = byte_count - total > (size_t)INT_MAX
                    ? INT_MAX
                    : (int)(byte_count - total);
    int transferred = 0;
    int error = libusb_bulk_transfer(transport->handle, transport->bulk_out_endpoint,
                                     (unsigned char *)bytes + total, chunk,
                                     &transferred, HPLJ_USB_TIMEOUT_MS);
    if (transferred > 0) {
      total += (size_t)transferred;
    }
    if (error != LIBUSB_SUCCESS) {
      return (struct hplj_transfer_result){hplj_libusb_error(error), total};
    }
    if (transferred == 0) {
      return (struct hplj_transfer_result){HPLJ_ERROR_TRANSFER_INCOMPLETE, total};
    }
  }
  return (struct hplj_transfer_result){HPLJ_ERROR_NONE, total};
}

static enum hplj_error_category hplj_libusb_upload(
    void *context, const unsigned char *firmware, size_t firmware_size) {
  return hplj_libusb_bulk_write(context, firmware, firmware_size).category;
}

static struct hplj_transfer_result hplj_libusb_write(
    void *context, const unsigned char *bytes, size_t byte_count) {
  return hplj_libusb_bulk_write(context, bytes, byte_count);
}

static enum hplj_error_category hplj_libusb_status(
    void *context, unsigned int *conditions) {
  struct hplj_libusb_transport *transport = context;
  unsigned char status = 0;
  int transferred = libusb_control_transfer(
      transport->handle,
      LIBUSB_ENDPOINT_IN | LIBUSB_REQUEST_TYPE_CLASS | LIBUSB_RECIPIENT_INTERFACE,
      HPLJ_PORT_STATUS_REQUEST, 0, (uint16_t)transport->interface_number,
      &status, sizeof(status), HPLJ_USB_TIMEOUT_MS);
  if (transferred < 0) {
    return hplj_libusb_error(transferred);
  }
  if (transferred != (int)sizeof(status)) {
    return HPLJ_ERROR_DEVICE_PROTOCOL;
  }
  *conditions = HPLJ_DEVICE_CONDITION_NONE;
  if ((status & (1U << 5)) != 0) {
    *conditions |= HPLJ_DEVICE_CONDITION_MEDIA_EMPTY;
  }
  if ((status & (1U << 4)) == 0) {
    *conditions |= HPLJ_DEVICE_CONDITION_NOT_SELECTED;
  }
  if ((status & (1U << 3)) == 0) {
    *conditions |= HPLJ_DEVICE_CONDITION_FAULT;
  }
  return HPLJ_ERROR_NONE;
}

enum hplj_error_category hplj_libusb_transport_create(
    struct hplj_libusb_transport **transport) {
  *transport = calloc(1, sizeof(**transport));
  if (*transport == NULL) {
    return HPLJ_ERROR_DEVICE_PROTOCOL;
  }
  (*transport)->interface_number = -1;
  (*transport)->alternate_setting = -1;
  enum hplj_error_category category =
      hplj_libusb_error(libusb_init(&(*transport)->context));
  if (category != HPLJ_ERROR_NONE) {
    free(*transport);
    *transport = NULL;
  }
  return category;
}

void hplj_libusb_transport_destroy(struct hplj_libusb_transport *transport) {
  if (transport == NULL) {
    return;
  }
  hplj_libusb_release(transport);
  if (transport->context != NULL) {
    libusb_exit(transport->context);
    transport->context = NULL;
  }
  free(transport);
}

void hplj_libusb_device_ops(struct hplj_libusb_transport *transport,
                            struct hplj_device_ops *ops) {
  *ops = (struct hplj_device_ops){
      .discover = hplj_libusb_discover,
      .open = hplj_libusb_open,
      .claim_interface = hplj_libusb_claim,
      .read_identity = hplj_libusb_identity,
      .upload_firmware = hplj_libusb_upload,
      .write = hplj_libusb_write,
      .read_status = hplj_libusb_status,
      .release = hplj_libusb_release,
      .context = transport,
  };
}
