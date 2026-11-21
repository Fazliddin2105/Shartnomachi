"""Imports every model so that `Base.metadata` is complete (Alembic, tests)."""

from app.modules.anchoring.models import AnchorBatch, AnchorLeaf  # noqa: F401
from app.modules.audit.models import AuditLog  # noqa: F401
from app.modules.auth.models import AuthSession, OtpCode  # noqa: F401
from app.modules.calc.models import BhmRate, CalendarDay  # noqa: F401
from app.modules.cases.models import CaseAttachment, CaseFile, CaseStep  # noqa: F401
from app.modules.contracts.models import (  # noqa: F401
    ClauseLibrary,
    Contract,
    ContractApproval,
    ContractParty,
    ContractType,
    ContractVersion,
)
from app.modules.files.models import StoredFile  # noqa: F401
from app.modules.mediation.models import MediationRequest  # noqa: F401
from app.modules.moderation.models import ContentReport, ContentTask  # noqa: F401
from app.modules.notifications.models import Notification  # noqa: F401
from app.modules.obligations.models import Obligation, Reminder  # noqa: F401
from app.modules.rules.models import LegalRule  # noqa: F401
from app.modules.scan.models import ScanFinding, ScanJob  # noqa: F401
from app.modules.templates.models import TemplateVersion  # noqa: F401
from app.modules.users.models import Company, CompanyMember, Profile, User  # noqa: F401
