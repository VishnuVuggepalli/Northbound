/**
 * Ergonomic aliases over the generated OpenAPI schema (`schema.gen.ts`).
 *
 * `schema.gen.ts` is auto-generated from the backend OpenAPI document
 * (`npm run gen:api`) — never edit it by hand. Import shared response/request
 * shapes from here so a backend contract change surfaces as a TypeScript error
 * at build time instead of a runtime surprise.
 */

import type { components } from './schema.gen';

export type Schemas = components['schemas'];

export type SettingsOut = Schemas['SettingsOut'];
export type SettingsPatch = Schemas['SettingsPatch'];
export type DeviceOut = Schemas['DeviceOut'];
export type PortStateOut = Schemas['PortStateOut'];
