from enum import Enum


class RecordType(str, Enum):
    PAYMENT_FAILED = "payment_failed"
    SUBSCRIPTION_FAILED = "subscription_failed"
    CHECKOUT_ABANDONED = "checkout_abandoned"
    INVOICE_OVERDUE = "invoice_overdue"


class Cause(str, Enum):
    BANK_DOWN = "bank_down"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    INSTRUMENT_EXPIRED = "instrument_expired"
    MANDATE_PAUSED = "mandate_paused"
    CHECKOUT_ABANDONED = "checkout_abandoned"
    INVOICE_UNPAID = "invoice_unpaid"
    CUSTOMER_CANCELLED = "customer_cancelled"
    FRAUD_FLAG = "fraud_flag"


class Action(str, Enum):
    WAIT_AUTO_RETRY = "wait_auto_retry"
    DELAY_RETRY = "delay_retry"
    UPDATE_INSTRUMENT_LINK = "update_instrument_link"
    REMANDATE_LINK = "remandate_link"
    CART_REMINDER_LINK = "cart_reminder_link"
    INVOICE_LINK = "invoice_link"
    STOP = "stop"


class Channel(str, Enum):
    NONE = "none"
    SYSTEM = "system"
    EMAIL = "email"
    SMS = "sms"
    VOICE = "voice"


class Policy(str, Enum):
    BASELINE = "baseline"
    AGENT = "agent"


class Outcome(str, Enum):
    RECOVERED = "recovered"
    NOT_RECOVERED = "not_recovered"
    SKIPPED = "skipped"
    QUEUED = "queued"
    POLICY_DENIED = "policy_denied"
    RAZORPAY_ERROR = "razorpay_error"
    VIOLATION = "violation"
    AWAITING_PAYMENT = "awaiting_payment"


CORRECT_ACTION: dict[Cause, Action] = {
    Cause.BANK_DOWN: Action.WAIT_AUTO_RETRY,
    Cause.INSUFFICIENT_FUNDS: Action.DELAY_RETRY,
    Cause.INSTRUMENT_EXPIRED: Action.UPDATE_INSTRUMENT_LINK,
    Cause.MANDATE_PAUSED: Action.REMANDATE_LINK,
    Cause.CHECKOUT_ABANDONED: Action.CART_REMINDER_LINK,
    Cause.INVOICE_UNPAID: Action.INVOICE_LINK,
    Cause.CUSTOMER_CANCELLED: Action.STOP,
    Cause.FRAUD_FLAG: Action.STOP,
}

LINK_ACTIONS = {
    Action.UPDATE_INSTRUMENT_LINK,
    Action.REMANDATE_LINK,
    Action.CART_REMINDER_LINK,
    Action.INVOICE_LINK,
}
