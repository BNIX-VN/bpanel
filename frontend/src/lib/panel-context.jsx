// What a page that is a file of its own reads from App (pages/WordPress.jsx):
// request, the loading flag, notices, navigation. App provides it around the
// page; BPanel's other pages still take props.
import { createContext, useContext } from 'react';

export const PanelContext = createContext({});

export function usePanel() {
  return useContext(PanelContext);
}
