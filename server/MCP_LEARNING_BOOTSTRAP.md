# Exile Architect — Learning server

Phase 7 comparative-learning campaign state, blind Create packets and the local append-only
Learning Memory. PoB/Judge tooling lives in the build server.

## Hard boundaries

1. One campaign has exactly one active case, strictly serial; CAS + explicit phase claims.
   Profile/Compare/Learn share one task; Create is a separate task and thread.
2. Blind Create packets contain only FamilyTarget, level and default goals — never reference
   gear, passives, skill groups, config, mechanisms or Judge results. Create never reads the
   reference case or its Judge scores. Final Create submission must carry both the complete
   claim-bound Global Research use and the Learning Memory use; Local, mixed, legacy or unbound
   Research receipts fail closed.
3. Judge scores are `advisoryOnly` attachments; the independent Comparator decides winners and
   the service never derives reward from Judge numbers.
4. Learning Memory is append-only: corrections append events and keep do-not-repeat history;
   never overwrite a prior lesson. Knowledge that fits a Research record kind must go to Research
   (`dbFit=false`).
5. No model calls, no Desktop task creation from this server.
