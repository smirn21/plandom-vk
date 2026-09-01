"""
YooKassa payment gateway client for subscription and request packages.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from typing import Any, Callable, Awaitable

import httpx

LOGGER = logging.getLogger(__name__)


class YooKassaClient:
    """Client for YooKassa payment gateway."""

    def __init__(self, shop_id: str, secret_key: str, test_mode: bool = False, webhook_secret: str | None = None):
        self.shop_id = shop_id
        self.secret_key = secret_key
        self.test_mode = test_mode
        self.webhook_secret = webhook_secret  # Secret key for webhook signature verification
        # YooKassa uses the same API URL for test and production
        self.base_url = "https://api.yookassa.ru/v3"
        self.auth = (shop_id, secret_key)

    async def create_payment(
        self,
        amount: float,
        description: str,
        return_url: str,
        user_id: str,
        payment_type: str,
        subscription_type: str | None = None,
        package_type: str | None = None,
        payment_method: str | None = None,
        payment_method_id: str | None = None,
        save_payment_method: bool = False,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Create payment in YooKassa.
        
        Args:
            amount: Amount in RUB
            description: Payment description
            return_url: URL to redirect after payment
            user_id: Telegram user ID
            payment_type: 'subscription' or 'package'
            subscription_type: 'month' or 'year' (for subscriptions)
            package_type: 'mini', 'standard', 'large', 'max' (for packages)
            payment_method: 'sbp' for СБП, None for default (card)
            payment_method_id: Saved payment method ID for autopayment
            save_payment_method: Whether to save payment method for future use
        
        Returns:
            Payment object with confirmation_url
        """
        # Use payment_id from YooKassa response for idempotency
        # Generate idempotence key, but use actual payment ID from response
        idempotence_key = str(uuid.uuid4())
        
        metadata = {
            "user_id": user_id,
            "payment_type": payment_type,
        }
        
        if subscription_type:
            metadata["subscription_type"] = subscription_type
        if package_type:
            metadata["package_type"] = package_type
        if project_id:
            metadata["project_id"] = project_id

        payload = {
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB",
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url,
            },
            "capture": True,
            "description": description,
            "metadata": metadata,
        }
        
        # Add payment method data
        if payment_method_id:
            # Use saved payment method for autopayment
            payload["payment_method_id"] = payment_method_id
        elif payment_method == "sbp":
            # Add СБП payment method
            payload["payment_method_data"] = {
                "type": "sbp"
            }
            # СБП: save_payment_method can only be used with saved payment methods
            # For new СБП payments, don't set save_payment_method if False
            # Only set it if explicitly True (user agreed to autopayment)
            if save_payment_method:
                payload["save_payment_method"] = True
        else:
            # For card payments: only set save_payment_method if True
            if save_payment_method:
                payload["save_payment_method"] = True

        headers = {
            "Idempotence-Key": idempotence_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/payments",
                json=payload,
                headers=headers,
                auth=self.auth,
            )
            
            # Log error details for debugging
            if response.status_code != 200:
                error_body = response.text
                LOGGER.error(
                    "YooKassa API error: status=%s, body=%s, payload=%s",
                    response.status_code,
                    error_body,
                    payload,
                )
            
            response.raise_for_status()
            data = response.json()
            
            # Use actual payment ID from YooKassa response (for idempotency)
            actual_payment_id = data["id"]
            
            LOGGER.info(
                "Created YooKassa payment: id=%s, amount=%.2f, type=%s, method=%s",
                actual_payment_id,
                amount,
                payment_type,
                payment_method or "card",
            )
            
            return data

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        """Get payment status from YooKassa."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/payments/{payment_id}",
                auth=self.auth,
            )
            response.raise_for_status()
            return response.json()

    async def handle_webhook(
        self,
        webhook_data: dict[str, Any],
        storage: Any,
        notify_user_callback: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        """
        Handle webhook notification from YooKassa.
        
        According to YooKassa documentation:
        - Webhook contains event type and payment/refund object
        - Event types: 'payment.succeeded', 'payment.canceled', 'payment.waiting_for_capture',
                       'refund.succeeded', 'refund.canceled', etc.
        - Payment object contains full payment information
        
        Args:
            webhook_data: Webhook payload from YooKassa
            storage: Storage instance for database operations
            notify_user_callback: Optional callback to notify user via bot
        """
        event_type = webhook_data.get("event")
        obj = webhook_data.get("object", {})
        payment_id = obj.get("id")
        status = obj.get("status")
        
        # Handle refund events
        if event_type and event_type.startswith("refund."):
            LOGGER.info("Refund event received: event=%s, refund_id=%s", event_type, payment_id)
            # Refunds are not currently implemented, but we log them
            if event_type == "refund.succeeded":
                LOGGER.info("Refund succeeded: %s", payment_id)
            elif event_type == "refund.canceled":
                LOGGER.info("Refund canceled: %s", payment_id)
            return
        
        if not payment_id:
            LOGGER.warning("Webhook received without payment ID: %s", webhook_data)
            return
        
        LOGGER.info(
            "Processing YooKassa webhook: event=%s, payment_id=%s, status=%s",
            event_type,
            payment_id,
            status,
        )
        
        # Verify payment status by fetching from API (recommended by YooKassa)
        try:
            payment_info = await self.get_payment(payment_id)
            verified_status = payment_info.get("status")
            metadata = payment_info.get("metadata", {})
            
            LOGGER.info(
                "Verified payment status: payment_id=%s, status=%s",
                payment_id,
                verified_status,
            )
            
            # Get payment data from DB
            payment_data = storage.get_payment_by_id(payment_id)
            
            # Handle different payment statuses
            if verified_status == "succeeded":
                # Check if payment was already processed
                from datetime import datetime
                paid_at = datetime.now().isoformat()
                
                if payment_data:
                    # Update existing payment
                    payment_data = storage.update_payment_status(payment_id, "succeeded", paid_at)
                else:
                    # Payment not in DB - might be from external source, log and skip
                    LOGGER.warning("Payment %s succeeded but not found in database", payment_id)
                    return
                
                user_id = payment_data["user_id"]
                payment_type = payment_data["payment_type"]
                
                if payment_type == "subscription":
                    # Activate subscription
                    subscription_type = payment_data["subscription_type"]
                    from datetime import timedelta
                    
                    if subscription_type == "month":
                        expires_at = (datetime.now() + timedelta(days=30)).isoformat()
                        requests_limit = 250
                    else:  # year
                        expires_at = (datetime.now() + timedelta(days=365)).isoformat()
                        requests_limit = 3500
                    
                    storage.set_subscription(user_id, "pro", expires_at, subscription_type)
                    
                    # Save payment method for autopayments if user agreed and payment method was saved
                    # ЮKassa автоматически сохраняет только те способы оплаты, которые поддерживают автоплатежи
                    payment_method = payment_info.get("payment_method", {})
                    if payment_method.get("saved") and payment_method.get("id"):
                        payment_method_id = payment_method["id"]
                        payment_method_type = payment_method.get("type", "")
                        # Сохраняем способ оплаты, если пользователь согласился на автопродление
                        # ЮKassa уже отфильтровал банки СБП, которые не поддерживают автоплатежи
                        if storage.is_auto_renewal_enabled(user_id):
                            storage.save_payment_method(user_id, payment_method_id)
                            LOGGER.info("Saved payment method %s (type: %s) for user %s (autopayment enabled)", payment_method_id, payment_method_type, user_id)
                        else:
                            LOGGER.info("Payment method saved by YooKassa but user didn't agree to autopayment, not storing")
                    
                    if notify_user_callback:
                        auto_renewal_msg = ""
                        has_autopay = storage.is_auto_renewal_enabled(user_id) and storage.get_saved_payment_method(user_id) is not None
                        if has_autopay:
                            auto_renewal_msg = "\n\n🔄 Автопродление включено. Подписка будет продлеваться автоматически."
                        
                        message = (
                            "✅ **Платеж успешно обработан!**\n\n"
                            f"🎉 Ваша подписка PRO активирована!\n\n"
                            f"📅 Действует до: {datetime.fromisoformat(expires_at).strftime('%d.%m.%Y')}\n"
                            f"📊 Доступно запросов: {requests_limit}"
                            + auto_renewal_msg
                            + "\n\nСпасибо за подписку! 🚀"
                        )
                        await notify_user_callback(user_id, message)
                    
                elif payment_type == "package":
                    # Add purchased requests
                    requests_count = payment_data["requests_count"]
                    if requests_count:
                        storage.add_purchased_requests(user_id, requests_count)
                        
                        if notify_user_callback:
                            message = (
                                "✅ **Платеж успешно обработан!**\n\n"
                                f"📦 Вам добавлено {requests_count} запросов\n\n"
                                f"Теперь вы можете использовать их для анализа растений! 🌱"
                            )
                            await notify_user_callback(user_id, message)
            
            elif verified_status == "canceled":
                storage.update_payment_status(payment_id, "canceled")
                LOGGER.info("Payment %s was canceled", payment_id)
                
                # Notify user about cancellation
                if payment_data and notify_user_callback:
                    user_id = payment_data["user_id"]
                    message = (
                        "❌ **Платеж отменен**\n\n"
                        "Ваш платеж был отменен.\n"
                        "Если вы хотите оформить подписку, попробуйте снова через меню «📊 Мой статус»."
                    )
                    await notify_user_callback(user_id, message)
            
            elif verified_status == "pending":
                # Payment is pending - update status but don't activate subscription
                storage.update_payment_status(payment_id, "pending")
                LOGGER.info("Payment %s is pending", payment_id)
            
            elif verified_status == "waiting_for_capture":
                # Two-stage payment waiting for capture
                storage.update_payment_status(payment_id, "waiting_for_capture")
                LOGGER.info("Payment %s is waiting for capture", payment_id)
                # Note: For subscriptions we use capture: True, so this shouldn't happen
                # But we handle it just in case
            
            elif verified_status == "failed":
                # Payment failed
                storage.update_payment_status(payment_id, "failed")
                LOGGER.warning("Payment %s failed", payment_id)
                
                # Notify user about failure
                if payment_data and notify_user_callback:
                    user_id = payment_data["user_id"]
                    failure_reason = payment_info.get("failure", {}).get("description", "Неизвестная причина")
                    message = (
                        "❌ **Платеж не прошел**\n\n"
                        f"Причина: {failure_reason}\n\n"
                        "Пожалуйста, проверьте данные карты и попробуйте снова.\n"
                        "Если проблема повторяется, обратитесь в поддержку."
                    )
                    await notify_user_callback(user_id, message)
                
        except Exception as exc:
            LOGGER.error("Error processing webhook for payment %s: %s", payment_id, exc, exc_info=True)
            raise

    def verify_webhook_signature(self, webhook_data: dict, signature: str | None = None) -> bool:
        """
        Verify webhook signature from YooKassa using HMAC-SHA256.
        
        According to YooKassa documentation:
        - Webhook signature is sent in HTTP header 'X-YooMoney-Signature'
        - Signature is computed as HMAC-SHA256 of webhook body using webhook secret key
        - Format: hex-encoded HMAC-SHA256 hash
        
        Args:
            webhook_data: Webhook payload (dict)
            signature: Signature from X-YooMoney-Signature header (optional, can be extracted from request)
        
        Returns:
            True if signature is valid or verification is skipped, False otherwise
        """
        if not self.webhook_secret:
            # If webhook secret is not configured, skip verification (not recommended for production)
            LOGGER.warning("Webhook secret not configured, skipping signature verification")
            return True
        
        if not signature:
            # Signature not provided - cannot verify
            LOGGER.warning("Webhook signature not provided")
            return False
        
        try:
            # Convert webhook data to JSON string (sorted keys for consistency)
            webhook_json = json.dumps(webhook_data, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            
            # Compute HMAC-SHA256
            computed_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                webhook_json.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures using constant-time comparison
            is_valid = hmac.compare_digest(computed_signature.lower(), signature.lower())
            
            if not is_valid:
                LOGGER.warning("Webhook signature verification failed")
            
            return is_valid
        except Exception as exc:
            LOGGER.error("Error verifying webhook signature: %s", exc, exc_info=True)
            return False
