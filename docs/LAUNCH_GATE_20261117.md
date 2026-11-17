# LOIAL — gates de lansare (17 noiembrie 2026)

## Decizii comerciale ferme
- Business: 67 EUR/lună, fără TVA adăugat în prezent.
- Wise Business: link de plată, fără API pentru pilot; creditarea numai după verificare manuală de către admin.
- Prima plată reală: 20 EUR ambasadorului care a adus firma + 10 EUR recrutorului direct al acelui ambasador, o singură dată per firmă.
- Reînnoiri: 5 EUR (1–25), 10 EUR (26–50), 15 EUR (51+) numai pentru ambasadorul care a adus firma și numai în lunile achitate.
- Fără comisioane către niveluri indirecte, fără bani pentru înregistrarea ambasadorului.
- Card PWA Black Metal instalabil independent de Apple/Google Wallet.
- Client către client: puncte pilot nemonetare, separate de ambasadori.

## Implementat în ramura de dezvoltare
- Înscriere firmă, înregistrare + login ambasador, linkuri referral.
- Ledger Wise verificat manual de administrator, referință unică, prevenire dubluri, aprobarea și marcarea externă a transferurilor.
- Calcul direct + recrutor, recomputare tier la reînnoiri, istoric privat ambasador, feed activitate admin.
- Export lunar .xlsx pentru comisioane și încasări reconciliate.
- Link Wise configurabil prin LOIAL_WISE_PAYMENT_URL; butonul rămâne ascuns până la configurare.
- Prețul public și interfața ajustate la 67 EUR fără TVA adăugat.
- Endpoint public nesecurizat /setup-admin dezactivat prin PR separat, deja integrat în main.

## Verificări executate
- GitHub Actions: execuție PASS (103 teste izolate + 1 test integrat în run #228).
- Verificare de sintaxă a JavaScript inline pentru index.html, join.html, ambasador.html, platform.html: PASS.
- Nu există dovadă de validare pentru toate funcțiile reale Wise, cardurile pe iPhone/Android și traficul simultan.

## Blocaje de lansare publică
1. Linkul de plată Wise Business real, administrat de proprietar; fără el butonul rămâne indisponibil.
2. Testarea cap-coadă pe un cont Business și două conturi de ambasador, cu tranzacție Wise reală de 67 EUR.
3. Valabilitatea abonamentelor, neplata/reînnoirea, anularea și reactivarea trebuie stabilite și testate, nu doar marcați în DB «probusiness» pentru totdeauna.
4. Verificarea securității pe întregul sistem, inclusiv rotația cheilor istorice, backup/restore DB, rate-limit înscriere și GDPR.
5. Test PWA pe Android și iPhone: instalare, păstrare token privat, recuperare portofel, scanări, recompense, caching offline.
6. Teste în producție pe loial.space și verificarea deploy; fără publicare automată până la aprobarea explicită a trecerii.
7. Loial AI Business necesită configurarea și controlul bugetului furnizorului de AI, dacă se comercializează inclus în plan.

## Reguli de siguranță la deploy
- Nu transfera automat bani din Wise, nu considera clickul de checkout o plată și nu permite activare ProBusiness fără dovadă.
- Nu activa Apple/Google Wallet ca dependențe pentru primele 100 de firme.
- Menține separarea și autorizarea datelor firmelor/ambasadorilor.
- Înainte de merge-ul ramurii de funcții: verifică diferențele față de main (inclusiv hotfix-ul admin), rulează CI pe commitul final și verifică migrarea DB în staging.

Acest document este un inventar verificabil, nu o declarație că LOIAL este deja public sau gata de încasări.
