// src/config/avatar-config.ts
// アバター定義の一元管理
// 将来のメニュー選択対応を見据えた設計

export interface AvatarDef {
  id: string;
  name: string;       // メニュー表示名
  modelUrl: string;   // public/avatar/ 配下のzipパス
}

/** 利用可能なアバター一覧 */
export const AVATARS: AvatarDef[] = [
  { id: 'meruru', name: 'メルル', modelUrl: '/avatar/meruru.zip' },
  { id: 'elf',    name: 'エルフ', modelUrl: '/avatar/elf.zip' },
];

/** モードごとのデフォルトアバターID */
export const MODE_DEFAULT_AVATAR: Record<string, string> = {
  lesson: 'meruru',
  concierge: 'elf',
};

/** IDからアバター定義を取得 */
export function getAvatarById(id: string): AvatarDef | undefined {
  return AVATARS.find(a => a.id === id);
}

/** モードのデフォルトアバターURLを取得 */
export function getDefaultAvatarUrl(mode: string): string {
  const avatarId = MODE_DEFAULT_AVATAR[mode] || 'meruru';
  const avatar = getAvatarById(avatarId);
  return avatar?.modelUrl || '/avatar/meruru.zip';
}
