import { requireNativeModule } from 'expo';
export type PhoneStatus = { accessibility: boolean; whatsapp: boolean; unlocked: boolean; running: boolean; journal: string; history: string[]; savedAccount: string };
export default requireNativeModule<{
  status(): PhoneStatus;
  permissions(): void;
  configure(server: string, token: string): void;
  credentials(): { server: string; token: string };
  rememberAccount(account: string): void;
  stage(job: string): void;
  execute(job: string): void;
  pause(): void;
  recover(): void;
}>('BeaconExecutor');
