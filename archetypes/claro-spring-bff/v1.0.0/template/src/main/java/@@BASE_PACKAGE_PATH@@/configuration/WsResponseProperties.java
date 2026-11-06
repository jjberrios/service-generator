package @@BASE_PACKAGE@@.configuration;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class WsResponseProperties {

    private final AuditValue idf0;
    private final AuditValue idf1;
    private final AuditValue idt1;
    private final AuditValue idt2;
    private final AuditValue idt3;
    private final AuditValue idt4;
    private final AuditValue idt5;

    public WsResponseProperties(
            @Value("${ws.codigoIdf0}") String codigoIdf0,
            @Value("${ws.mensajeIdf0}") String mensajeIdf0,
            @Value("${ws.detailIdf0}") String detailIdf0,
            @Value("${ws.codigoIdf1}") String codigoIdf1,
            @Value("${ws.mensajeIdf1}") String mensajeIdf1,
            @Value("${ws.detailIdf1}") String detailIdf1,
            @Value("${ws.codigoIdt1}") String codigoIdt1,
            @Value("${ws.mensajeIdt1}") String mensajeIdt1,
            @Value("${ws.detailIdt1}") String detailIdt1,
            @Value("${ws.codigoIdt2}") String codigoIdt2,
            @Value("${ws.mensajeIdt2}") String mensajeIdt2,
            @Value("${ws.detailIdt2}") String detailIdt2,
            @Value("${ws.codigoIdt3}") String codigoIdt3,
            @Value("${ws.mensajeIdt3}") String mensajeIdt3,
            @Value("${ws.detailIdt3}") String detailIdt3,
            @Value("${ws.codigoIdt4}") String codigoIdt4,
            @Value("${ws.mensajeIdt4}") String mensajeIdt4,
            @Value("${ws.detailIdt4}") String detailIdt4,
            @Value("${ws.codigoIdt5}") String codigoIdt5,
            @Value("${ws.mensajeIdt5}") String mensajeIdt5,
            @Value("${ws.detailIdt5}") String detailIdt5) {
        this.idf0 = new AuditValue(codigoIdf0, mensajeIdf0, detailIdf0);
        this.idf1 = new AuditValue(codigoIdf1, mensajeIdf1, detailIdf1);
        this.idt1 = new AuditValue(codigoIdt1, mensajeIdt1, detailIdt1);
        this.idt2 = new AuditValue(codigoIdt2, mensajeIdt2, detailIdt2);
        this.idt3 = new AuditValue(codigoIdt3, mensajeIdt3, detailIdt3);
        this.idt4 = new AuditValue(codigoIdt4, mensajeIdt4, detailIdt4);
        this.idt5 = new AuditValue(codigoIdt5, mensajeIdt5, detailIdt5);
    }


    public AuditValue idf0() { return idf0; }
    public AuditValue idf1() { return idf1; }
    public AuditValue idt1() { return idt1; }
    public AuditValue idt2() { return idt2; }
    public AuditValue idt3() { return idt3; }
    public AuditValue idt4() { return idt4; }
    public AuditValue idt5() { return idt5; }

    public record AuditValue(String subType, String message, String detail) {
    }
}
