// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef HPLJ_USB_LIBUSB_H
#define HPLJ_USB_LIBUSB_H

#include "hplj/device.h"

struct hplj_libusb_transport;

enum hplj_error_category hplj_libusb_transport_create(
    struct hplj_libusb_transport **transport);
void hplj_libusb_transport_destroy(struct hplj_libusb_transport *transport);
void hplj_libusb_device_ops(struct hplj_libusb_transport *transport,
                            struct hplj_device_ops *ops);

#endif
