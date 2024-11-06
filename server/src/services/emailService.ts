import { Resend } from 'resend';

const resend = new Resend(process.env.RESEND_API_KEY);

export const sendEmail = async (to: string, subject: string, html: string) => {
    try {
        const data = await resend.emails.send({
            from: 'Verdad <notifications@verdad.app>',
            to,
            subject,
            html,
        });
        return data;
    } catch (error) {
        console.error('Error sending email:', error);
        throw error;
    }
};
