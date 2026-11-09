import {webcrypto} from 'node:crypto';
globalThis.crypto ||= webcrypto;
import {importOwnerKey,issueLicense} from '../dist/activation-crypto.mjs';
let input='';for await(const chunk of process.stdin)input+=chunk;
const value=JSON.parse(input);const key=await importOwnerKey(value.pem,value.public_key);
process.stdout.write(await issueLicense(key,value.machine,value.issued_at));
