import test from 'node:test';
import assert from 'node:assert/strict';
import { safeCsvValue } from '../src/safeCsv.ts';

test('untrusted spreadsheet formula prefixes are made literal', () => {
 for (const value of ['=HYPERLINK("https://example.invalid","click")','+SUM(1,2)','-2+3','@SUM(A1:A2)','\tcustomer claim','\rmalicious field','\n=SUM(1,2)','  =1+1','\ufeff=1+1']) {
  assert.equal(safeCsvValue(value),"'"+value);
 }
});

test('ordinary text and numeric values remain readable', () => {
 for (const [value,expected] of [['Arrived cracked','Arrived cracked'],['customer, quoted "claim"','customer, quoted "claim"'],[500,'500'],[null,''],[undefined,'']]) {
  assert.equal(safeCsvValue(value),expected);
 }
});
