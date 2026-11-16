"""Google Wallet-first 100-merchant pilot metrics.

Read-only. No issuer API calls, emails, or expenses. Counts distinct merchants
with at least one recorded loyalty award, NOT arbitrary signups as 'active'.
Only the platform administrator should invoke the attached endpoint.
"""
import os
from sqlalchemy import func

from loial_google_issuer import configured_issuer, valid_class_id
from loial_scans import StampAward

PILOT_GOAL=100

def google_pilot_snapshot(db, BusinessAccount, Customer):
    registered=db.query(func.count(BusinessAccount.id)).scalar() or 0
    awarded={row[0] for row in db.query(StampAward.business_id).distinct().all()}
    enrolled={row[0] for row in db.query(Customer.business_id).distinct().all()}
    # "Active" has the strict, observable meaning of one recorded stamp award.
    active=db.query(BusinessAccount).filter(
        BusinessAccount.id.in_(awarded)).count() if awarded else 0
    issued=db.query(BusinessAccount).filter(
        BusinessAccount.id.in_(enrolled)).count() if enrolled else 0
    issuer=configured_issuer() is not None
    loyalty_class=valid_class_id(os.getenv("LOIAL_GOOGLE_LOYALTY_CLASS_ID",""))
    ambassador_class=valid_class_id(os.getenv("LOIAL_GOOGLE_AMBASSADOR_CLASS_ID",""))
    sync_enabled=os.getenv("LOIAL_GOOGLE_WALLET_SYNC_ENABLED","0")=="1"
    return {
        "goal_active_businesses":PILOT_GOAL,
        "businesses_registered":registered,
        "businesses_with_customer_cards":issued,
        "businesses_with_recorded_stamp_awards":active,
        "remaining_to_goal":max(0,PILOT_GOAL-active),
        "goal_reached":active>=PILOT_GOAL,
        "google_wallet":{
            "issuer_credentials_present":issuer,
            "loyalty_class_id_configured":loyalty_class,
            "ambassador_class_id_configured":ambassador_class,
            "merchant_specific_classes_enabled":os.getenv("LOIAL_GOOGLE_MERCHANT_CLASSES","0")=="1",
            "automatic_updates_enabled":sync_enabled and issuer and loyalty_class,
            "publishing_approved":"not_verified",
            "note":"Aprobarea pentru publicare se confirma in Google Pay & Wallet Console; prezenta cheii nu dovedeste aprobarea."
        },
        "apple_wallet":{
            "in_pilot":False,
            "reason":"Dupa 100 de firme active, numai daca este aprobata prioritatea."
        },
        "definition":"Firma activa = firma distincta cu cel putin o acordare de stampila in jurnalul Loial. Nu reprezinta automat un abonament platit.",
        "extra_costs_authorized":False
    }
