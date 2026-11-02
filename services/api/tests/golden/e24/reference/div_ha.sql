-- E24-T06 reference: the half-away-from-zero integer division macro funding_basis.sql uses.
CREATE OR REPLACE MACRO div_ha(a, b) AS
  sign(a) * sign(b) * ((2 * abs(a) + abs(b)) // (2 * abs(b)));
